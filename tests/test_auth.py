import re

from itsdangerous import URLSafeTimedSerializer
import pytest

from app import db


def test_every_route_requires_login_or_is_allowlisted(app):
    from app.auth import PUBLIC
    c = app.test_client()
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC:
            continue
        url = re.sub(r"<[^>]+>", "1", rule.rule)
        for m in rule.methods - {"HEAD", "OPTIONS"}:
            r = c.open(url, method=m, base_url="https://localhost")
            assert r.status_code == 302 and "/login" in r.headers["Location"], (rule.rule, m)


def test_public_allowlist_is_exactly_login_register_health_static(app):
    from app.auth import PUBLIC
    assert PUBLIC == {"auth.login_form", "auth.login_submit", "auth.register", "healthz", "static"}


def test_register_without_valid_csrf_token_is_refused(app):
    c = app.test_client()
    r = c.post("/register", base_url="https://localhost", data={
        "token": "forged-csrf-token",
        "email": "test@company.com",
        "password": "ValidPassword123!",
        "role": "owner"
    })
    assert r.status_code == 400
    assert "Session expired" in r.get_data(as_text=True)


def test_register_password_too_short_is_refused(app):
    c = app.test_client()
    tok = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="register-csrf").dumps("x")
    r = c.post("/register", base_url="https://localhost", data={
        "token": tok,
        "email": "test@company.com",
        "password": "short",
        "role": "owner"
    })
    assert r.status_code == 400
    assert "Password must be at least 12 characters." in r.get_data(as_text=True)


def test_register_admin_role_escalation_is_refused(app):
    c = app.test_client()
    tok = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="register-csrf").dumps("x")
    r = c.post("/register", base_url="https://localhost", data={
        "token": tok,
        "email": "hacker@company.com",
        "password": "StrongPassword123!",
        "role": "admin"
    })
    assert r.status_code == 400
    assert "Invalid role selected" in r.get_data(as_text=True)


def test_register_duplicate_email_is_refused(app, monkeypatch):
    monkeypatch.setattr(db, "one", lambda sql, args=None: {"id": 1, "email": "exists@company.com"})
    c = app.test_client()
    tok = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="register-csrf").dumps("x")
    r = c.post("/register", base_url="https://localhost", data={
        "token": tok,
        "email": "exists@company.com",
        "password": "StrongPassword123!",
        "role": "owner"
    })
    assert r.status_code == 400
    assert "already exists" in r.get_data(as_text=True)


def test_register_success(app, monkeypatch):
    import app.routes.auth_routes as ar
    monkeypatch.setattr(db, "one", lambda sql, args=None: None)
    monkeypatch.setattr(ar, "create_user", lambda email, pw, role: {"id": 42, "email": email, "role": role})
    monkeypatch.setattr(ar, "audit", lambda *a, **k: None)

    class DummyConn:
        def commit(self): pass
        def rollback(self): pass

    monkeypatch.setattr(db, "conn", lambda: DummyConn())
    c = app.test_client()
    tok = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="register-csrf").dumps("x")
    r = c.post("/register", base_url="https://localhost", data={
        "token": tok,
        "email": "newuser@company.com",
        "password": "StrongPassword123!",
        "role": "owner"
    })
    assert r.status_code == 200
    assert "Account created successfully" in r.get_data(as_text=True)


def test_register_authenticated_user_redirects_to_documents(app, monkeypatch):
    monkeypatch.setattr(db, "one", lambda sql, args=None: {"sid": "sid1", "csrf": "csrf1", "id": 10, "email": "u@test.local", "role": "owner"})
    monkeypatch.setattr(db, "run", lambda sql, args=None: None)
    c = app.test_client()
    c.set_cookie("tv_session", "valid-test-cookie")
    r = c.get("/register", base_url="https://localhost")
    assert r.status_code == 302
    assert "/documents" in r.headers["Location"]


def test_register_real_db_workflow(app):
    from itsdangerous import URLSafeTimedSerializer
    import secrets
    from tests.conftest import APP_URL
    if not APP_URL:
        pytest.skip("TEST_DATABASE_URL not set")

    c = app.test_client()
    tok = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="register-csrf").dumps("x")
    unique_email = f"user-{secrets.token_hex(4)}@company.com"
    pw = "SuperSecurePassword123!"

    # 1. Successful registration
    r = c.post("/register", base_url="https://localhost", data={
        "token": tok,
        "email": unique_email,
        "password": pw,
        "role": "owner"
    })
    assert r.status_code == 200
    assert "Account created successfully" in r.get_data(as_text=True)

    # 2. Verify in PostgreSQL
    with app.app_context():
        u = db.one("SELECT id, email, role, active FROM users WHERE email = %s", (unique_email,))
        assert u is not None
        assert u["role"] == "owner"
        assert u["active"] is True
        assert isinstance(u["id"], int)

    # 3. Duplicate email rejection against real PostgreSQL
    tok2 = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="register-csrf").dumps("x")
    r2 = c.post("/register", base_url="https://localhost", data={
        "token": tok2,
        "email": unique_email,
        "password": pw,
        "role": "owner"
    })
    assert r2.status_code == 400
    assert "already exists" in r2.get_data(as_text=True)

    # 4. Attempt admin role escalation against real PostgreSQL
    admin_attempt_email = f"hacker-{secrets.token_hex(4)}@company.com"
    tok3 = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="register-csrf").dumps("x")
    r3 = c.post("/register", base_url="https://localhost", data={
        "token": tok3,
        "email": admin_attempt_email,
        "password": pw,
        "role": "admin"
    })
    assert r3.status_code == 400
    with app.app_context():
        admin_check = db.one("SELECT id FROM users WHERE email = %s", (admin_attempt_email,))
        assert admin_check is None


def test_post_without_csrf_token_is_rejected(alice, doc):
    assert alice.post(f"/documents/{doc}/delete", csrf=False).status_code == 400
    assert alice.get(f"/documents/{doc}/download").status_code == 200       # not deleted


def test_logout_kills_the_session(alice):
    assert alice.get("/documents").status_code == 200
    alice.post("/logout")
    assert alice.get("/documents").status_code == 302


def test_disabled_user_session_dies_immediately(app, bob, admin):
    assert bob.get("/documents").status_code == 200
    assert admin.post(f"/admin/users/{bob.id}/disable").status_code == 302
    assert bob.get("/documents").status_code == 302
    assert bob.login().status_code == 401


def test_session_cookie_flags(app, alice):
    alice.c.delete_cookie("tv_session")
    r = alice.c.get("/login", base_url=alice.base)
    page = r.get_data(as_text=True)
    resp = app.test_client().post("/login", base_url="https://localhost", data={
        "login_token": re.search(r'name="login_token" value="([^"]+)"', page).group(1),
        "email": alice.email, "password": alice.password})
    cookie = resp.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie


def test_lockout_after_repeated_failures(app, alice):
    from tests.conftest import Client
    bad = Client(app, alice.email, "wrong-password")
    for _ in range(5):
        assert bad.login().status_code == 401
    assert alice.login().status_code == 401          # correct password, but the account is locked
    with app.app_context():
        db.run("UPDATE users SET locked_until=NULL, failed_logins=0 WHERE id=%s", (alice.id,))
        db.conn().commit()


def test_login_without_valid_token_is_refused(app):
    r = app.test_client().post("/login", base_url="https://localhost",
                               data={"login_token": "forged", "email": "a@b.c", "password": "x"})
    assert r.status_code == 400


def test_security_headers(alice):
    r = alice.get("/documents")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"
