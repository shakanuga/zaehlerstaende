import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from fake_pocketid import FakePocketID  # noqa: E402
from zaehler import pocketid  # noqa: E402
from zaehler.app import create_app  # noqa: E402

H = {"X-Zaehler": "1"}


def setup_oidc(app, **extra):
    fake = FakePocketID()
    app.config["POCKETID"] = pocketid.PocketID(fake.env(**extra), opener=fake)
    return fake


def sign_in(fake, c, user=None, next_url="/"):
    res = c.get("/auth/pocketid?next=" + urllib.parse.quote(next_url))
    assert res.status_code == 302
    redirect, params = fake.login(res.headers["Location"], user)
    assert redirect == "http://localhost/auth/pocketid/zurueck"
    return c.get("/auth/pocketid/zurueck?" + urllib.parse.urlencode(params))


def make(tmp_path):
    app = create_app(str(tmp_path / "data"), str(tmp_path / "import"))
    admin = app.test_client()
    assert admin.post("/api/setup", json={"username": "chef", "password": "geheim1234"}, headers=H).status_code == 200
    assert admin.post("/api/users", json={"username": "mama", "password": "geheim1234"}, headers=H).status_code == 201
    return app


def test_linked_by_username_then_by_sub(tmp_path):
    app = make(tmp_path)
    fake = setup_oidc(app)
    c = app.test_client()
    assert c.get("/api/state").json["oidc"]["enabled"]
    res = sign_in(fake, c, {"preferred_username": "Mama"}, "/#/statistik")
    assert res.headers["Location"] == "/#/statistik"
    assert c.get("/api/state").json["user"]["username"] == "mama"
    c2 = app.test_client()
    sign_in(fake, c2, {"preferred_username": "umbenannt"})
    assert c2.get("/api/state").json["user"]["username"] == "mama"


def test_unknown_user_rejected_and_password_switch(tmp_path):
    app = make(tmp_path)
    fake = setup_oidc(app, OIDC_DISABLE_PASSWORD="1")
    c = app.test_client()
    res = sign_in(fake, c, {"sub": "x", "preferred_username": "fremd"})
    assert res.headers["Location"].startswith("/?fehler=")
    assert c.get("/api/state").json["user"] is None
    assert c.post("/api/login", json={"username": "chef", "password": "geheim1234"}, headers=H).status_code == 403


def test_first_login_becomes_admin(tmp_path):
    app = create_app(str(tmp_path / "data"), str(tmp_path / "import"))
    fake = setup_oidc(app)
    c = app.test_client()
    sign_in(fake, c)
    user = c.get("/api/state").json["user"]
    assert user["admin"] and user["record"]


def test_deactivated_user_cannot_sign_in(tmp_path):
    app = make(tmp_path)
    fake = setup_oidc(app)
    import sqlite3
    con = sqlite3.connect(tmp_path / "data" / "zaehler.sqlite3")
    con.execute("UPDATE users SET active=0 WHERE username='mama'")
    con.commit()
    c = app.test_client()
    res = sign_in(fake, c, {"preferred_username": "mama"})
    assert "deaktiviert" in urllib.parse.unquote(res.headers["Location"])
