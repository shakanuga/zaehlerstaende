"""Zählerstand: Flask-Anwendung."""
import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
import time
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, abort, g, jsonify, request, send_file, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db, exports, importer, ocr, photos, stats

SESSION_DAYS = 180
COOKIE = "zaehler_session"
MAX_FAILS = 5
LOCK_SECONDS = 60
COLORS = ("gas", "strom", "wasser", "neutral")


def now():
    return datetime.now().isoformat(timespec="seconds")


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
        test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
    except ValueError:
        return False
    return secrets.compare_digest(test.hex(), digest)


def parse_value(raw):
    text = str(raw).strip().replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    value = float(text)
    if not 0 <= value < 1e12:
        raise ValueError
    return round(value, 4)


def parse_date(raw):
    day = date.fromisoformat(str(raw)[:10])
    if day > date.today():
        raise ValueError
    return day.isoformat()


def fail(message, status=400, **extra):
    res = jsonify(error=message, **extra)
    res.status_code = status
    return res


def create_app(data_dir=None, import_dir=None):
    data_dir = data_dir or os.environ.get("ZAEHLER_DATA", "/data")
    import_dir = import_dir or os.environ.get("ZAEHLER_IMPORT", "/import")
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "zaehler.sqlite3")
    db.init(db_path)

    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    fails = {}

    def con():
        if "db" not in g:
            g.db = db.connect(db_path)
        return g.db

    @app.teardown_appcontext
    def close(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def current_user():
        if "user" in g:
            return g.user
        g.user = None
        token = request.cookies.get(COOKIE)
        if token:
            row = con().execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
                "WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
                (hashlib.sha256(token.encode()).hexdigest(), now()),
            ).fetchone()
            g.user = row
        return g.user

    def is_admin():
        user = current_user()
        return bool(user and user["role"] == "admin")

    def can_record():
        user = current_user()
        return bool(user and (user["role"] == "admin" or user["can_record"]))

    def login_required(fn):
        @wraps(fn)
        def inner(*a, **k):
            if not current_user():
                return fail("Bitte anmelden.", 401)
            return fn(*a, **k)
        return inner

    def admin_required(fn):
        @wraps(fn)
        def inner(*a, **k):
            if not current_user():
                return fail("Bitte anmelden.", 401)
            if not is_admin():
                abort(404)
            return fn(*a, **k)
        return inner

    def recorder_required(fn):
        @wraps(fn)
        def inner(*a, **k):
            if not current_user():
                return fail("Bitte anmelden.", 401)
            if not can_record():
                return fail("Dein Konto darf keine Stände eintragen.", 403)
            return fn(*a, **k)
        return inner

    @app.before_request
    def csrf_guard():
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.path.startswith("/api/"):
            if request.headers.get("X-Zaehler") != "1":
                return fail("Ungültige Anfrage.", 403)
        return None

    @app.after_request
    def security_headers(res):
        res.headers["X-Content-Type-Options"] = "nosniff"
        res.headers["Referrer-Policy"] = "same-origin"
        res.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'"
        )
        if request.path.startswith("/api/") and "Cache-Control" not in res.headers:
            res.headers["Cache-Control"] = "no-store"
        return res

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return fail("Nicht gefunden.", 404)
        return send_from_directory(static_dir, "index.html")

    @app.errorhandler(413)
    def too_large(_e):
        return fail("Die Datei ist zu groß.", 413)

    # ---- Sichtbarkeit: jeder Zugriff auf Zähler läuft hier durch ----------
    def visible_meters(include_inactive=False):
        where = "1=1" if is_admin() else "private=0"
        if not include_inactive:
            where += " AND active=1"
        return con().execute(f"SELECT * FROM meters WHERE {where} ORDER BY sort, id").fetchall()

    def meter_or_404(meter_id):
        row = con().execute("SELECT * FROM meters WHERE id=?", (meter_id,)).fetchone()
        if not row or (row["private"] and not is_admin()):
            abort(404)
        return row

    def reading_or_404(reading_id):
        row = con().execute(
            "SELECT * FROM readings WHERE id=? AND deleted_at IS NULL", (reading_id,)
        ).fetchone()
        if not row:
            abort(404)
        meter_or_404(row["meter_id"])
        return row

    def meter_json(row):
        data = dict(row)
        data["private"] = bool(row["private"])
        data["active"] = bool(row["active"])
        if not is_admin():
            data.pop("private")
            data.pop("parent_id")
        return data

    def meter_readings(meter_id):
        return con().execute(
            "SELECT * FROM readings WHERE meter_id=? AND deleted_at IS NULL ORDER BY read_on", (meter_id,)
        ).fetchall()

    def current_photo(reading_id):
        return con().execute(
            "SELECT * FROM photos WHERE reading_id=? AND superseded_at IS NULL ORDER BY id DESC LIMIT 1",
            (reading_id,),
        ).fetchone()

    def photo_json(row):
        if not row:
            return None
        return {"id": row["id"], "sha256": row["sha256"], "taken_at": row["taken_at"],
                "uploaded_at": row["uploaded_at"], "size": row["size"]}

    def log(action, reading=None, old=None, new=None, reason="", meter_id=None):
        user = current_user()
        con().execute(
            "INSERT INTO audit(at,user_id,user_name,action,meter_id,reading_id,old_json,new_json,reason) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (now(), user["id"] if user else None, user["display_name"] if user else "System", action,
             meter_id or (reading["meter_id"] if reading else None), reading["id"] if reading else None,
             json.dumps(old, ensure_ascii=False) if old else None,
             json.dumps(new, ensure_ascii=False) if new else None, reason),
        )

    @app.get("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(static_dir, name, max_age=3600)

    # ---- Anmeldung ---------------------------------------------------------
    @app.get("/api/state")
    def state():
        needs_setup = not con().execute("SELECT 1 FROM users LIMIT 1").fetchone()
        user = current_user()
        return jsonify(
            setup=needs_setup,
            user=None if not user else {
                "id": user["id"], "name": user["display_name"], "username": user["username"],
                "admin": is_admin(), "record": can_record(),
            },
            ocr=bool(ocr.provider()),
            today=date.today().isoformat(),
        )

    def start_session(user_id):
        token = secrets.token_urlsafe(32)
        expires = datetime.now() + timedelta(days=SESSION_DAYS)
        con().execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
        con().execute(
            "INSERT INTO sessions VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, expires.isoformat(timespec="seconds")),
        )
        res = jsonify(ok=True)
        res.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                       samesite="Lax", secure=request.is_secure)
        return res

    @app.post("/api/setup")
    def setup():
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", "")).strip()
        name = str(body.get("name", "")).strip() or username
        password = str(body.get("password", ""))
        if not username or len(password) < 8:
            return fail("Benutzername und ein Passwort mit mindestens 8 Zeichen eingeben.")
        conn = con()
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            conn.rollback()
            return fail("Die Einrichtung ist schon abgeschlossen.", 403)
        cur = conn.execute(
            "INSERT INTO users(username,display_name,password_hash,role,can_record,created_at) "
            "VALUES (?,?,?,'admin',1,?)", (username, name, hash_password(password), now()),
        )
        res = start_session(cur.lastrowid)
        conn.commit()
        return res

    @app.post("/api/login")
    def login():
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", "")).strip()
        key = (request.remote_addr, username.lower())
        count, since = fails.get(key, (0, 0))
        if count >= MAX_FAILS and time.time() - since < LOCK_SECONDS:
            return fail("Zu viele Versuche. Bitte eine Minute warten.", 429)
        row = con().execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if not row or not check_password(str(body.get("password", "")), row["password_hash"]):
            fails[key] = (1 if count >= MAX_FAILS else count + 1, time.time())
            return fail("Benutzername oder Passwort stimmt nicht.", 401)
        fails.pop(key, None)
        res = start_session(row["id"])
        con().commit()
        return res

    @app.post("/api/logout")
    def logout():
        token = request.cookies.get(COOKIE)
        if token:
            con().execute("DELETE FROM sessions WHERE token_hash=?",
                          (hashlib.sha256(token.encode()).hexdigest(),))
            con().commit()
        res = jsonify(ok=True)
        res.delete_cookie(COOKIE)
        return res

    @app.post("/api/password")
    @login_required
    def change_password():
        body = request.get_json(silent=True) or {}
        new = str(body.get("new", ""))
        if not check_password(str(body.get("old", "")), current_user()["password_hash"]):
            return fail("Das aktuelle Passwort stimmt nicht.", 403)
        if len(new) < 8:
            return fail("Das neue Passwort braucht mindestens 8 Zeichen.")
        con().execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), current_user()["id"]))
        con().commit()
        return jsonify(ok=True)

    # ---- Zähler und Übersicht ----------------------------------------------
    @app.get("/api/meters")
    @login_required
    def meters():
        return jsonify([meter_json(m) for m in visible_meters()])

    @app.get("/api/overview")
    @login_required
    def overview():
        today = date.today()
        month = today.strftime("%Y-%m")
        out = []
        for meter in visible_meters():
            rows = meter_readings(meter["id"])
            summary = stats.summary(rows)
            last = rows[-1] if rows else None
            last_iv = summary["intervals"][-1] if summary["intervals"] else None
            photo = current_photo(last["id"]) if last else None
            this_month = [r for r in rows if r["read_on"].startswith(month)]
            spark = [{"month": m["month"], "value": m["value"], "full": m["full"]} for m in summary["months"][-13:]]
            out.append({
                "meter": meter_json(meter),
                "last": None if not last else {
                    "id": last["id"], "read_on": last["read_on"], "value": last["value"],
                    "photo": photo["id"] if photo else None,
                },
                "last_interval": last_iv,
                "done": this_month[0]["read_on"] if this_month else None,
                "ytd": summary["ytd"], "spark": spark, "count": len(rows),
            })
        return jsonify(month=month, meters=out)

    # ---- Ablesungen --------------------------------------------------------
    def reading_rows(meter):
        rows = meter_readings(meter["id"])
        by_end = {iv["end"]: iv for iv in stats.intervals(rows)}
        result = []
        for row in rows:
            photo = current_photo(row["id"])
            iv = by_end.get(row["read_on"])
            result.append({
                "id": row["id"], "read_on": row["read_on"], "value": row["value"],
                "new_meter": bool(row["new_meter"]), "note": row["note"],
                "delta": iv["delta"] if iv else None, "days": iv["days"] if iv else None,
                "per_day": iv["per_day"] if iv else None, "ok": iv["ok"] if iv else True,
                "photo": photo["id"] if photo else None,
            })
        return result

    @app.get("/api/meters/<int:meter_id>/readings")
    @login_required
    def list_readings(meter_id):
        meter = meter_or_404(meter_id)
        return jsonify(meter=meter_json(meter), readings=list(reversed(reading_rows(meter))))

    def neighbours(meter_id, read_on, exclude=None):
        rows = [r for r in meter_readings(meter_id) if r["id"] != exclude]
        before = [r for r in rows if r["read_on"] < read_on]
        after = [r for r in rows if r["read_on"] > read_on]
        return (before[-1] if before else None), (after[0] if after else None), rows

    def warnings_for(meter_id, value, read_on, new_meter, exclude=None):
        prev, nxt, rows = neighbours(meter_id, read_on, exclude)
        return stats.plausibility(value, read_on, new_meter, prev, nxt, stats.intervals(rows)[-12:])

    @app.post("/api/photo/inspect")
    @recorder_required
    def inspect_photo():
        file = request.files.get("photo")
        if not file:
            return fail("Kein Foto übermittelt.")
        data = file.read()
        try:
            _, taken_at = photos.inspect(data)
        except photos.PhotoError as exc:
            return fail(str(exc))
        suggestion = None
        meter_id = request.form.get("meter_id", type=int)
        if meter_id and ocr.provider():
            meter = meter_or_404(meter_id)
            rows = meter_readings(meter_id)
            suggestion = ocr.recognize(data, meter, rows[-1]["value"] if rows else None)
        return jsonify(taken_at=taken_at, suggestion=suggestion)

    def attach_photo(reading, data, name):
        info = photos.store(data_dir, data, name)
        con().execute("UPDATE photos SET superseded_at=? WHERE reading_id=? AND superseded_at IS NULL",
                      (now(), reading["id"]))
        con().execute(
            "INSERT INTO photos(reading_id,path,original_name,mime,size,sha256,taken_at,uploaded_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (reading["id"], info["path"], info["original_name"], info["mime"], info["size"],
             info["sha256"], info["taken_at"], now()),
        )
        return info

    @app.post("/api/meters/<int:meter_id>/readings")
    @recorder_required
    def create_reading(meter_id):
        meter = meter_or_404(meter_id)
        form = request.form
        try:
            value = parse_value(form.get("value", ""))
            read_on = parse_date(form.get("read_on", ""))
        except ValueError:
            return fail("Stand oder Datum ist ungültig. Das Datum darf nicht in der Zukunft liegen.")
        new_meter = form.get("new_meter") == "1"
        file = request.files.get("photo")
        data = file.read() if file else None
        if data:
            try:
                photos.inspect(data)
            except photos.PhotoError as exc:
                return fail(str(exc))
        warnings = warnings_for(meter_id, value, read_on, new_meter)
        if warnings and form.get("confirm") != "1":
            return fail("Bitte prüfen.", 409, warnings=warnings)
        conn = con()
        try:
            cur = conn.execute(
                "INSERT INTO readings(meter_id,read_on,value,new_meter,note,created_by,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (meter_id, read_on, value, int(new_meter), form.get("note", "")[:500],
                 current_user()["id"], now()),
            )
        except sqlite3.IntegrityError:
            return fail(f"Für diesen Tag gibt es schon einen Stand bei {meter['name']}.", 409, duplicate=True)
        reading = conn.execute("SELECT * FROM readings WHERE id=?", (cur.lastrowid,)).fetchone()
        info = attach_photo(reading, data, file.filename) if data else None
        log("angelegt", reading, new={"read_on": read_on, "value": value, "new_meter": new_meter,
                                      "foto_sha256": info["sha256"] if info else None})
        conn.commit()
        return jsonify(id=reading["id"], warnings=warnings), 201

    @app.get("/api/readings/<int:reading_id>")
    @login_required
    def reading_detail(reading_id):
        row = reading_or_404(reading_id)
        meter = meter_or_404(row["meter_id"])
        entry = next(r for r in reading_rows(meter) if r["id"] == reading_id)
        history = con().execute(
            "SELECT at,user_name,action,old_json,new_json,reason FROM audit WHERE reading_id=? ORDER BY id DESC",
            (reading_id,),
        ).fetchall()
        creator = con().execute("SELECT display_name FROM users WHERE id=?", (row["created_by"],)).fetchone()
        all_photos = con().execute("SELECT * FROM photos WHERE reading_id=? ORDER BY id DESC", (reading_id,)).fetchall()
        return jsonify(
            meter=meter_json(meter), reading=entry,
            created_at=row["created_at"], created_by=creator["display_name"] if creator else "Import",
            photo=photo_json(current_photo(reading_id)),
            old_photos=[photo_json(p) for p in all_photos if p["superseded_at"]],
            history=[{
                "at": h["at"], "user": h["user_name"], "action": h["action"], "reason": h["reason"],
                "old": json.loads(h["old_json"]) if h["old_json"] else None,
                "new": json.loads(h["new_json"]) if h["new_json"] else None,
            } for h in history],
        )

    @app.post("/api/readings/<int:reading_id>")
    @recorder_required
    def update_reading(reading_id):
        row = reading_or_404(reading_id)
        body = request.get_json(silent=True) or {}
        try:
            value = parse_value(body.get("value", row["value"]))
            read_on = parse_date(body.get("read_on", row["read_on"]))
        except ValueError:
            return fail("Stand oder Datum ist ungültig. Das Datum darf nicht in der Zukunft liegen.")
        new_meter = bool(body.get("new_meter", row["new_meter"]))
        note = str(body.get("note", row["note"]))[:500]
        warnings = warnings_for(row["meter_id"], value, read_on, new_meter, reading_id)
        if warnings and not body.get("confirm"):
            return fail("Bitte prüfen.", 409, warnings=warnings)
        old = {"read_on": row["read_on"], "value": row["value"], "new_meter": bool(row["new_meter"]), "note": row["note"]}
        new = {"read_on": read_on, "value": value, "new_meter": new_meter, "note": note}
        if old == new:
            return jsonify(ok=True)
        try:
            con().execute(
                "UPDATE readings SET read_on=?,value=?,new_meter=?,note=?,updated_at=? WHERE id=?",
                (read_on, value, int(new_meter), note, now(), reading_id),
            )
        except sqlite3.IntegrityError:
            return fail("Für diesen Tag gibt es schon einen Stand.", 409)
        log("geändert", row, old, new, str(body.get("reason", ""))[:300])
        con().commit()
        return jsonify(ok=True)

    @app.post("/api/readings/<int:reading_id>/photo")
    @recorder_required
    def replace_photo(reading_id):
        row = reading_or_404(reading_id)
        file = request.files.get("photo")
        if not file:
            return fail("Kein Foto übermittelt.")
        try:
            info = attach_photo(row, file.read(), file.filename)
        except photos.PhotoError as exc:
            return fail(str(exc))
        log("Foto ergänzt", row, new={"foto_sha256": info["sha256"]})
        con().commit()
        return jsonify(ok=True)

    @app.delete("/api/readings/<int:reading_id>")
    @admin_required
    def delete_reading(reading_id):
        row = reading_or_404(reading_id)
        con().execute("UPDATE readings SET deleted_at=? WHERE id=?", (now(), reading_id))
        log("gelöscht", row, old={"read_on": row["read_on"], "value": row["value"]})
        con().commit()
        return jsonify(ok=True)

    @app.get("/api/photos/<int:photo_id>/<size>")
    @login_required
    def photo_file(photo_id, size):
        row = con().execute(
            "SELECT p.*, r.meter_id FROM photos p JOIN readings r ON r.id=p.reading_id "
            "WHERE p.id=? AND r.deleted_at IS NULL", (photo_id,),
        ).fetchone()
        if not row or size not in ("thumb", "view", "original"):
            abort(404)
        meter_or_404(row["meter_id"])
        if size == "original":
            res = send_file(os.path.join(data_dir, "photos", row["path"]), mimetype=row["mime"],
                            download_name=f"zaehlerfoto-{row['id']}{os.path.splitext(row['path'])[1]}")
        else:
            try:
                path = photos.derived(data_dir, row["id"], row["path"], size)
            except OSError:
                abort(404)
            res = send_file(path, mimetype="image/jpeg")
        res.headers["Cache-Control"] = "private, max-age=86400"
        return res

    # ---- Statistik ---------------------------------------------------------
    @app.get("/api/meters/<int:meter_id>/stats")
    @login_required
    def meter_stats(meter_id):
        meter = meter_or_404(meter_id)
        rows = meter_readings(meter_id)
        result = stats.summary(rows)
        result["meter"] = meter_json(meter)
        if is_admin() and meter["parent_id"]:
            parent = meter_or_404(meter["parent_id"])
            result["parent"] = {
                "name": parent["name"],
                "rows": stats.compare_parent(
                    stats.daily(stats.intervals(rows)),
                    stats.daily(stats.intervals(meter_readings(parent["id"]))),
                ),
            }
        return jsonify(result)

    # ---- Export ------------------------------------------------------------
    def export_data(meter_ids=None, start=None, end=None):
        out = []
        for meter in visible_meters(include_inactive=True):
            if meter_ids and meter["id"] not in meter_ids:
                continue
            entries = []
            for row in reading_rows(meter):
                if (start and row["read_on"] < start) or (end and row["read_on"] > end):
                    continue
                photo = con().execute("SELECT * FROM photos WHERE id=?", (row["photo"],)).fetchone() if row["photo"] else None
                entries.append({**row, "photo_row": dict(photo) if photo else None})
            out.append({"meter": dict(meter), "readings": entries})
        return out

    def changed_entries(data):
        ids = [r["id"] for block in data for r in block["readings"]]
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return con().execute(
            f"SELECT a.*, r.read_on, m.name AS meter_name FROM audit a JOIN readings r ON r.id=a.reading_id "
            f"JOIN meters m ON m.id=r.meter_id WHERE a.reading_id IN ({marks}) AND a.action='geändert' ORDER BY a.id",
            ids,
        ).fetchall()

    @app.get("/api/export.xlsx")
    @login_required
    def export_xlsx():
        data = export_data()
        path = exports.workbook(data, request.host_url.rstrip("/"), tempfile.mkdtemp(dir=_tmp()))
        return send_file(path, as_attachment=True, download_name=f"zaehlerstaende-{date.today()}.xlsx")

    @app.get("/api/nachweis.pdf")
    @login_required
    def export_pdf():
        meter_id = request.args.get("meter", type=int)
        meter = meter_or_404(meter_id)
        start, end = request.args.get("from") or None, request.args.get("to") or None
        data = export_data({meter["id"]}, start, end)
        if not data[0]["readings"]:
            return fail("In diesem Zeitraum gibt es keine Ablesungen.", 404)
        path = exports.proof_pdf(
            data[0], changed_entries(data), start, end, current_user()["display_name"],
            lambda pid, rel: photos.derived(data_dir, pid, rel, "view"), tempfile.mkdtemp(dir=_tmp()),
        )
        return send_file(path, as_attachment=True, download_name=f"nachweis-{meter['key']}-{date.today()}.pdf")

    def _tmp():
        path = os.path.join(data_dir, "tmp")
        os.makedirs(path, exist_ok=True)
        return path

    # ---- Verwaltung --------------------------------------------------------
    def user_json(row):
        return {"id": row["id"], "username": row["username"], "name": row["display_name"],
                "role": row["role"], "can_record": bool(row["can_record"]), "active": bool(row["active"])}

    @app.get("/api/users")
    @admin_required
    def users():
        return jsonify([user_json(u) for u in con().execute("SELECT * FROM users ORDER BY id")])

    @app.post("/api/users")
    @admin_required
    def create_user():
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        role = "admin" if body.get("role") == "admin" else "member"
        if not username or len(password) < 8:
            return fail("Benutzername und ein Passwort mit mindestens 8 Zeichen eingeben.")
        try:
            con().execute(
                "INSERT INTO users(username,display_name,password_hash,role,can_record,created_at) VALUES (?,?,?,?,?,?)",
                (username, str(body.get("name", "")).strip() or username, hash_password(password), role,
                 int(bool(body.get("can_record"))), now()),
            )
        except sqlite3.IntegrityError:
            return fail("Diesen Benutzernamen gibt es schon.", 409)
        con().commit()
        return jsonify(ok=True), 201

    @app.post("/api/users/<int:user_id>")
    @admin_required
    def update_user(user_id):
        row = con().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            abort(404)
        body = request.get_json(silent=True) or {}
        role = body.get("role", row["role"])
        active = bool(body.get("active", row["active"]))
        if row["role"] == "admin" and row["active"] and (role != "admin" or not active):
            admins = con().execute("SELECT COUNT(*) c FROM users WHERE role='admin' AND active=1").fetchone()["c"]
            if admins <= 1:
                return fail("Es muss mindestens ein aktives Admin-Konto bleiben.")
        password = body.get("password")
        if password is not None and len(str(password)) < 8:
            return fail("Das Passwort braucht mindestens 8 Zeichen.")
        con().execute(
            "UPDATE users SET display_name=?,role=?,can_record=?,active=?,password_hash=? WHERE id=?",
            (str(body.get("name", row["display_name"])).strip() or row["display_name"],
             "admin" if role == "admin" else "member", int(bool(body.get("can_record", row["can_record"]))),
             int(active), hash_password(str(password)) if password else row["password_hash"], user_id),
        )
        if not active or password:
            con().execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        con().commit()
        return jsonify(ok=True)

    def meter_fields(body, row=None):
        get = lambda k, d: body.get(k, row[k] if row else d)
        name, unit = str(get("name", "")).strip(), str(get("unit", "")).strip()
        decimals = int(get("decimals", 3))
        color = get("color", "neutral")
        parent = get("parent_id", None) or None
        if not name or not unit or not 0 <= decimals <= 4 or color not in COLORS:
            raise ValueError
        if parent is not None:
            parent = int(parent)
            if not con().execute("SELECT 1 FROM meters WHERE id=?", (parent,)).fetchone() or (row and parent == row["id"]):
                raise ValueError
        return (name, unit, decimals, color, int(bool(get("private", 0))), parent, int(get("sort", 100)),
                int(bool(get("active", 1))), str(get("number", ""))[:60])

    @app.get("/api/meters/all")
    @admin_required
    def all_meters():
        return jsonify([meter_json(m) for m in visible_meters(include_inactive=True)])

    @app.post("/api/meters")
    @admin_required
    def create_meter():
        body = request.get_json(silent=True) or {}
        try:
            fields = meter_fields(body)
        except (ValueError, TypeError):
            return fail("Name, Einheit und Nachkommastellen (0 bis 4) prüfen.")
        key = f"z{secrets.token_hex(4)}"
        con().execute(
            "INSERT INTO meters(name,unit,decimals,color,private,parent_id,sort,active,number,key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*fields, key),
        )
        con().commit()
        return jsonify(ok=True), 201

    @app.post("/api/meters/<int:meter_id>")
    @admin_required
    def update_meter(meter_id):
        row = meter_or_404(meter_id)
        try:
            fields = meter_fields(request.get_json(silent=True) or {}, row)
        except (ValueError, TypeError):
            return fail("Name, Einheit und Nachkommastellen (0 bis 4) prüfen.")
        con().execute(
            "UPDATE meters SET name=?,unit=?,decimals=?,color=?,private=?,parent_id=?,sort=?,active=?,number=? WHERE id=?",
            (*fields, meter_id),
        )
        con().commit()
        return jsonify(ok=True)

    @app.get("/api/audit")
    @admin_required
    def audit():
        rows = con().execute(
            "SELECT a.*, m.name AS meter_name, r.read_on FROM audit a "
            "LEFT JOIN meters m ON m.id=a.meter_id LEFT JOIN readings r ON r.id=a.reading_id "
            "ORDER BY a.id DESC LIMIT 200"
        ).fetchall()
        return jsonify([{
            "at": r["at"], "user": r["user_name"], "action": r["action"], "meter": r["meter_name"],
            "read_on": r["read_on"], "reading_id": r["reading_id"], "reason": r["reason"],
            "old": json.loads(r["old_json"]) if r["old_json"] else None,
            "new": json.loads(r["new_json"]) if r["new_json"] else None,
        } for r in rows])

    def import_meters():
        return {m["key"]: m for m in con().execute("SELECT * FROM meters")}

    @app.post("/api/import/preview")
    @admin_required
    def import_preview():
        file = request.files.get("file")
        if not file:
            return fail("Keine Excel-Datei übermittelt.")
        token = secrets.token_hex(12)
        path = os.path.join(_tmp(), f"import-{token}.xlsx")
        file.save(path)
        try:
            plan = importer.parse(path, import_dir)
        except importer.ImportProblem as exc:
            os.unlink(path)
            return fail(str(exc))
        existing = {(r["meter_id"], r["read_on"]) for r in con().execute(
            "SELECT meter_id, read_on FROM readings WHERE deleted_at IS NULL")}
        return jsonify(token=token, **importer.preview(plan, import_meters(), existing))

    @app.post("/api/import/commit")
    @admin_required
    def import_commit():
        token = str((request.get_json(silent=True) or {}).get("token", ""))
        if not token.isalnum():
            return fail("Ungültige Anfrage.")
        path = os.path.join(_tmp(), f"import-{token}.xlsx")
        if not os.path.exists(path):
            return fail("Die Vorschau ist abgelaufen. Bitte die Datei noch einmal wählen.", 404)
        plan = importer.parse(path, import_dir)
        meters_by_key = import_meters()
        conn = con()
        added = with_photo = 0
        for item in plan["readings"]:
            meter = meters_by_key[item["meter"]]
            if conn.execute("SELECT 1 FROM readings WHERE meter_id=? AND read_on=? AND deleted_at IS NULL",
                            (meter["id"], item["read_on"])).fetchone():
                continue
            cur = conn.execute(
                "INSERT INTO readings(meter_id,read_on,value,note,created_by,created_at) VALUES (?,?,?,?,?,?)",
                (meter["id"], item["read_on"], item["value"], "Aus Excel übernommen", current_user()["id"], now()),
            )
            reading = conn.execute("SELECT * FROM readings WHERE id=?", (cur.lastrowid,)).fetchone()
            if item.get("photo_bytes"):
                try:
                    attach_photo(reading, item["photo_bytes"], item.get("photo_name", ""))
                    with_photo += 1
                except photos.PhotoError:
                    pass
            log("importiert", reading, new={"read_on": item["read_on"], "value": item["value"]})
            added += 1
        conn.commit()
        os.unlink(path)
        return jsonify(added=added, with_photo=with_photo)

    return app
