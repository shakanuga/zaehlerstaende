import io
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from openpyxl import Workbook
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from zaehler import ocr, stats  # noqa: E402
from zaehler.app import create_app  # noqa: E402

H = {"X-Zaehler": "1"}


def jpeg(color=(40, 90, 120), exif_date=None):
    img = Image.new("RGB", (800, 600), color)
    out = io.BytesIO()
    if exif_date:
        ex = img.getexif()
        ex[0x0132] = exif_date
        img.save(out, "JPEG", exif=ex)
    else:
        img.save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def env(tmp_path):
    app = create_app(str(tmp_path / "data"), str(tmp_path / "import"))
    admin = app.test_client()
    assert admin.post("/api/setup", json={"username": "chef", "password": "geheim1234"}, headers=H).status_code == 200
    assert admin.post("/api/users", json={"username": "mama", "password": "geheim1234", "can_record": True},
                      headers=H).status_code == 201
    assert admin.post("/api/users", json={"username": "gast", "password": "geheim1234"}, headers=H).status_code == 201
    def client(name):
        c = app.test_client()
        assert c.post("/api/login", json={"username": name, "password": "geheim1234"}, headers=H).status_code == 200
        return c
    return admin, client("mama"), client("gast"), tmp_path


def meter(c, key):
    return next(m for m in c.get("/api/meters").json if m["key"] == key)


def add(c, mid, day, value, photo=True, **extra):
    data = {"read_on": day, "value": value, **extra}
    if photo:
        data["photo"] = (io.BytesIO(jpeg()), "z.jpg")
    return c.post(f"/api/meters/{mid}/readings", data=data, headers=H, content_type="multipart/form-data")


def test_stats_splits_across_months():
    rows = [
        {"id": 1, "read_on": "2026-01-01", "value": 0.0, "new_meter": 0},
        {"id": 2, "read_on": "2026-02-03", "value": 33.0, "new_meter": 0},
        {"id": 3, "read_on": "2026-03-01", "value": 59.0, "new_meter": 0},
    ]
    s = stats.summary(rows)
    jan, feb = s["months"]
    assert jan["value"] == 31 and jan["full"]
    assert feb["value"] == 28 and feb["full"]


def test_stats_meter_swap_does_not_go_negative():
    rows = [
        {"id": 1, "read_on": "2026-01-01", "value": 900.0, "new_meter": 0},
        {"id": 2, "read_on": "2026-02-01", "value": 931.0, "new_meter": 0},
        {"id": 3, "read_on": "2026-03-01", "value": 2.0, "new_meter": 1},
        {"id": 4, "read_on": "2026-03-11", "value": 12.0, "new_meter": 0},
    ]
    s = stats.summary(rows)
    assert [iv["delta"] for iv in s["intervals"]] == [31.0, 10.0]
    assert s["bad_intervals"] == 0


def test_stats_year_compare_only_when_prev_covered():
    rows = [{"id": i, "read_on": d, "value": v, "new_meter": 0} for i, (d, v) in enumerate(
        [("2025-01-01", 0.0), ("2026-01-01", 365.0), ("2026-02-01", 415.0)])]
    y = stats.summary(rows)["ytd"]
    assert y["value"] == 50 and y["prev_value"] == 31 and y["pct"] == pytest.approx(61.3)
    y2 = stats.summary(rows[1:])["ytd"]
    assert y2["prev_value"] is None


def test_parent_compare_flags_stuck_meter():
    sub = stats.daily(stats.intervals([
        {"id": 1, "read_on": "2026-01-01", "value": 5.0, "new_meter": 0},
        {"id": 2, "read_on": "2026-02-01", "value": 5.0, "new_meter": 0}]))
    main = stats.daily(stats.intervals([
        {"id": 1, "read_on": "2026-01-01", "value": 10.0, "new_meter": 0},
        {"id": 2, "read_on": "2026-02-01", "value": 20.0, "new_meter": 0}]))
    row = stats.compare_parent(sub, main)[0]
    assert row["stuck"] and row["share"] == 0


def test_parent_compare_flags_unusually_low_month():
    def days(steps):
        rows, value = [], 0.0
        for month, inc in enumerate(steps, 1):
            rows.append({"id": month, "read_on": f"2026-{month:02d}-01", "value": value, "new_meter": 0})
            value += inc
        return stats.daily(stats.intervals(rows))
    rows = stats.compare_parent(days([2, 2, 2, 0.2, 2, 2, 0]), days([8, 8, 8, 8, 8, 8, 0]))
    assert [r["month"] for r in rows if r["low"]] == ["2026-04"]


def test_private_meter_is_invisible_everywhere(env):
    admin, mama, gast, _ = env
    secret = meter(admin, "wasser_klein")
    assert secret["private"] is True
    assert add(admin, secret["id"], "2026-01-01", "10").status_code == 201
    assert add(admin, secret["id"], "2026-02-01", "11").status_code == 201
    rid = admin.get(f"/api/meters/{secret['id']}/readings").json["readings"][0]["id"]
    pid = admin.get(f"/api/readings/{rid}").json["photo"]["id"]
    assert admin.get(f"/api/photos/{pid}/original").status_code == 200
    for c in (mama, gast):
        keys = [m["key"] for m in c.get("/api/meters").json]
        assert "wasser_klein" not in keys and "gas" in keys
        assert "wasser_klein" not in c.get("/api/overview").get_data(as_text=True)
        assert c.get(f"/api/meters/{secret['id']}/readings").status_code == 404
        assert c.get(f"/api/meters/{secret['id']}/stats").status_code == 404
        assert c.get(f"/api/readings/{rid}").status_code == 404
        assert c.get(f"/api/photos/{pid}/thumb").status_code == 404
        assert c.get(f"/api/photos/{pid}/original").status_code == 404
        assert c.get(f"/api/nachweis.pdf?meter={secret['id']}").status_code == 404
        assert c.post(f"/api/readings/{rid}", json={"value": 1}, headers=H).status_code in (403, 404)
        assert add(c, secret["id"], "2026-03-01", "12").status_code in (403, 404)
        assert c.get("/api/audit").status_code == 404
        assert c.get("/api/users").status_code == 404
        wb_bytes = c.get("/api/export.xlsx").data
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(wb_bytes))
        text = " ".join(str(v) for ws in wb for row in ws.iter_rows(values_only=True) for v in row)
        assert "Kleiner" not in text
    wiped = admin.get("/api/export.xlsx").data
    assert b"PK" == wiped[:2]


def test_parent_data_not_in_public_meter_stats(env):
    admin, mama, *_ = env
    wasser = meter(admin, "wasser")
    assert add(admin, wasser["id"], "2026-01-01", "10").status_code == 201
    body = mama.get(f"/api/meters/{wasser['id']}/stats").get_data(as_text=True)
    assert "parent" not in body and "Kleiner" not in body


def test_view_only_user_cannot_record(env):
    admin, mama, gast, _ = env
    gas = meter(admin, "gas")
    assert add(gast, gas["id"], "2026-01-01", "10").status_code == 403
    assert add(mama, gas["id"], "2026-01-01", "10").status_code == 201


def test_logged_out_gets_nothing(env):
    admin, *_, tmp = env
    gas = meter(admin, "gas")
    add(admin, gas["id"], "2026-01-01", "10")
    app = create_app(str(tmp / "data"), str(tmp / "import"))
    anon = app.test_client()
    for url in ("/api/meters", "/api/overview", f"/api/meters/{gas['id']}/stats", "/api/export.xlsx",
                "/api/photos/1/original", "/api/users"):
        assert anon.get(url).status_code == 401


def test_post_needs_header(env):
    admin, *_ = env
    assert admin.post("/api/logout").status_code == 403


def test_plausibility_and_duplicate(env):
    admin, *_ = env
    gas = meter(admin, "gas")
    add(admin, gas["id"], "2026-01-01", "100")
    low = add(admin, gas["id"], "2026-02-01", "90")
    assert low.status_code == 409 and low.json["warnings"][0]["code"] == "lower"
    assert add(admin, gas["id"], "2026-02-01", "90", confirm="1").status_code == 201
    assert add(admin, gas["id"], "2026-02-01", "95").status_code == 409
    assert add(admin, gas["id"], (date.today() + timedelta(days=2)).isoformat(), "95").status_code == 400
    assert add(admin, gas["id"], "2026-03-01", "abc").status_code == 400
    assert add(admin, gas["id"], "2026-03-01", "1.234,5", new_meter="1").status_code == 201
    assert admin.get(f"/api/meters/{gas['id']}/readings").json["readings"][0]["value"] == 1234.5


def test_bad_upload_rejected(env):
    admin, *_ = env
    gas = meter(admin, "gas")
    res = admin.post(f"/api/meters/{gas['id']}/readings",
                     data={"read_on": "2026-01-01", "value": "1", "photo": (io.BytesIO(b"<script>"), "x.jpg")},
                     headers=H, content_type="multipart/form-data")
    assert res.status_code == 400
    assert admin.get(f"/api/meters/{gas['id']}/readings").json["readings"] == []


def test_edit_keeps_history_and_old_photo(env):
    admin, mama, *_ = env
    gas = meter(admin, "gas")
    add(mama, gas["id"], "2026-01-01", "100")
    rid = admin.get(f"/api/meters/{gas['id']}/readings").json["readings"][0]["id"]
    assert mama.post(f"/api/readings/{rid}", json={"value": "101", "reason": "Tippfehler"}, headers=H).status_code == 200
    mama.post(f"/api/readings/{rid}/photo", data={"photo": (io.BytesIO(jpeg((9, 9, 9))), "n.jpg")},
              headers=H, content_type="multipart/form-data")
    d = admin.get(f"/api/readings/{rid}").json
    assert [h["action"] for h in d["history"]] == ["Foto ergänzt", "geändert", "angelegt"]
    assert d["history"][1]["old"]["value"] == 100 and d["history"][1]["reason"] == "Tippfehler"
    assert len(d["old_photos"]) == 1
    assert mama.delete(f"/api/readings/{rid}", headers=H).status_code == 404
    assert admin.delete(f"/api/readings/{rid}", headers=H).status_code == 200
    assert any(a["action"] == "gelöscht" for a in admin.get("/api/audit").json)


def test_photo_original_unchanged_and_hash(env):
    import hashlib
    admin, *_ = env
    gas = meter(admin, "gas")
    raw = jpeg(exif_date="2026:01:02 09:15:00")
    admin.post(f"/api/meters/{gas['id']}/readings",
               data={"read_on": "2026-01-02", "value": "1", "photo": (io.BytesIO(raw), "a.jpg")},
               headers=H, content_type="multipart/form-data")
    rid = admin.get(f"/api/meters/{gas['id']}/readings").json["readings"][0]["id"]
    p = admin.get(f"/api/readings/{rid}").json["photo"]
    assert p["taken_at"] == "2026-01-02T09:15:00"
    assert admin.get(f"/api/photos/{p['id']}/original").data == raw
    assert p["sha256"] == hashlib.sha256(raw).hexdigest()
    assert admin.get(f"/api/photos/{p['id']}/view").mimetype == "image/jpeg"


def test_import_old_excel(env):
    admin, _, _, tmp = env
    folder = tmp / "import"
    (folder / "2024").mkdir(parents=True)
    (folder / "2024" / "gas_jan.jpg").write_bytes(jpeg())
    wb = Workbook()
    ws = wb.active
    ws.append(["Datum", "Gas in m³", "Diff", "Foto", "Strom kWh", "Diff", "Foto", "Wasser", "Diff", "Foto", "Klein"])
    ws.append([date(2024, 1, 2), 100.5, None, "gas_jan.jpg", 2000, None, None, 50.25, None, "fehlt.jpg", 3.5])
    ws.append(["03.02.2024", "110,5", 10, None, "2.100", 100, None, 52, 1.75, None, None])
    ws.append([date(2024, 3, 1), 105, -5, None, None, None, None, None, None, None, None])
    ws.append(["kein Datum", 1, None, None, None, None, None, None, None, None, None])
    ws["D2"].hyperlink = r"\\nas\data\Zaehler\2024\gas_jan.jpg"
    path = tmp / "alt.xlsx"
    wb.save(path)
    with open(path, "rb") as fh:
        res = admin.post("/api/import/preview", data={"file": (fh, "alt.xlsx")}, headers=H,
                         content_type="multipart/form-data")
    assert res.status_code == 200, res.json
    plan = res.json
    gas = next(m for m in plan["meters"] if m["name"] == "Gas")
    assert gas["count"] == 3 and gas["photos"] == 1 and gas["drops"] == ["2024-03-01"]
    assert plan["missing_photos"] == ["Zeile 2, Wasser Hauptzähler: fehlt.jpg"] and plan["problem_count"] == 1
    assert admin.post("/api/import/commit", json={"token": plan["token"]}, headers=H).json == {"added": 8, "with_photo": 1}
    strom = meter(admin, "strom")
    assert admin.get(f"/api/meters/{strom['id']}/readings").json["readings"][0]["value"] == 2100


def test_exports(env):
    admin, *_ = env
    gas = meter(admin, "gas")
    add(admin, gas["id"], "2026-01-01", "100")
    add(admin, gas["id"], "2026-02-02", "131.5")
    rid = admin.get(f"/api/meters/{gas['id']}/readings").json["readings"][0]["id"]
    admin.post(f"/api/readings/{rid}", json={"value": "131.6", "reason": "Rolle falsch gelesen"}, headers=H)
    pdf = admin.get(f"/api/nachweis.pdf?meter={gas['id']}")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert admin.get(f"/api/nachweis.pdf?meter={gas['id']}&from=2030-01-01").status_code == 404
    assert admin.get("/api/export.xlsx").status_code == 200


def test_last_admin_stays(env):
    admin, *_ = env
    assert admin.post("/api/users/1", json={"active": False}, headers=H).status_code == 400
    assert admin.post("/api/users/1", json={"role": "member"}, headers=H).status_code == 400


def test_login_lock(env):
    *_, tmp = env
    app = create_app(str(tmp / "data"), str(tmp / "import"))
    c = app.test_client()
    for _ in range(5):
        assert c.post("/api/login", json={"username": "chef", "password": "x"}, headers=H).status_code == 401
    assert c.post("/api/login", json={"username": "chef", "password": "geheim1234"}, headers=H).status_code == 429


def test_second_setup_refused(env):
    *_, tmp = env
    app = create_app(str(tmp / "data"), str(tmp / "import"))
    assert app.test_client().post("/api/setup", json={"username": "x", "password": "12345678"}, headers=H).status_code == 403


def test_ocr_parsing_and_off_by_default(monkeypatch):
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    assert ocr.provider() is None and ocr.recognize(jpeg(), {"name": "Gas", "unit": "m³", "decimals": 3}) is None
    assert ocr._value('```json\n{"value": 123.45}\n```') == 123.45
    assert ocr._value('{"value": null}') is None and ocr._value("keine Ahnung") is None


def test_ocr_both_providers_against_fake_server(monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = {}

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen[self.path] = (body, self.headers.get("x-api-key"))
            answer = ({"content": [{"type": "text", "text": '{"value": 4711.25}'}]}
                      if self.path == "/v1/messages" else {"response": '{"value": 815.5}'})
            raw = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    meter_info = {"name": "Gas", "unit": "m³", "decimals": 3}
    monkeypatch.setenv("OCR_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_URL", url)
    assert ocr.recognize(jpeg(), meter_info, 4700) == 4711.25
    body, key = seen["/v1/messages"]
    assert key == "k" and body["messages"][0]["content"][0]["type"] == "image"
    monkeypatch.setenv("OCR_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_URL", url)
    monkeypatch.setenv("OLLAMA_MODEL", "m")
    assert ocr.recognize(jpeg(), meter_info) == 815.5
    server.shutdown()
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    assert ocr.recognize(jpeg(), meter_info) is None


def test_import_small_meter_photo_same_names_and_bad_link(tmp_path):
    from zaehler import importer
    folder = tmp_path / "import"
    for name, color in (("Gas", (1, 1, 1)), ("Strom", (2, 2, 2)), ("Wasser (Hauptzähler)", (3, 3, 3)), ("Wasser (Klein)", (4, 4, 4))):
        (folder / name).mkdir(parents=True)
        (folder / name / "a.jpg").write_bytes(jpeg(color))
    wb = Workbook()
    ws = wb.active
    ws.append(["Datum", "Gas", "Diff", "Foto", "Strom", "Diff", "Foto", "Wasser", "Diff", "Foto", "Klein", "Diff", "Foto"])
    ws.append([date(2025, 9, 12), 1, None, "a.jpg", 2, None, "a.jpg", 3, None, "a.jpg", 4, None, "a.jpg"])
    ws.append([date(2025, 10, 1), 2, 1, "Link", 3, 1, '=HYPERLINK("\\\\nas\\x\\Strom\\a.jpg";"Link")', 4, 1, None, 5, 1, None])
    ws.cell(2, 13).hyperlink = r"\\nas\appdata\Wasser (Klein)\a.jpg"
    path = tmp_path / "a.xlsx"
    wb.save(path)
    plan = importer.parse(str(path), str(folder))
    got = {(r["row"], r["meter"]): r.get("photo_bytes") for r in plan["readings"]}
    assert got[(2, "gas")] == jpeg((1, 1, 1))
    assert got[(2, "strom")] == jpeg((2, 2, 2))
    assert got[(2, "wasser")] == jpeg((3, 3, 3))
    assert got[(2, "wasser_klein")] == jpeg((4, 4, 4))
    assert got[(3, "strom")] == jpeg((2, 2, 2))
    assert plan["missing_photos"] == ["Zeile 3, Gas: Link"]


def test_import_small_meter_photo_in_column_l(tmp_path):
    from zaehler import importer
    folder = tmp_path / "import"
    folder.mkdir()
    (folder / "k.jpg").write_bytes(jpeg())
    wb = Workbook()
    ws = wb.active
    ws.append(["Datum", "Gas", "Diff", "Foto", "Strom", "Diff", "Foto", "Wasser", "Diff", "Foto", "Klein", "Foto"])
    ws.append([date(2025, 9, 12), None, None, None, None, None, None, None, None, None, 4, "k.jpg"])
    ws.append([date(2025, 10, 1), None, None, None, None, None, None, None, None, None, 5, 1.5])
    path = tmp_path / "a.xlsx"
    wb.save(path)
    plan = importer.parse(str(path), str(folder))
    assert plan["readings"][0].get("photo_bytes") and not plan["readings"][1].get("photo_bytes")
    assert plan["missing_photos"] == []
