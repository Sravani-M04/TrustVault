from flask import Blueprint, current_app, g, make_response, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .. import auth, db
from ..audit import audit
from ..users import create_user

bp = Blueprint("auth", __name__)
DUMMY_HASH = generate_password_hash("not-a-real-password")   # equalise timing for unknown emails


def _login_token():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="login-csrf").dumps("x")


def _login_token_ok(tok):
    try:
        URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="login-csrf").loads(tok, max_age=900)
        return True
    except BadSignature:
        return False


def _reg_token():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="register-csrf").dumps("x")


def _reg_token_ok(tok):
    try:
        URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="register-csrf").loads(tok, max_age=900)
        return True
    except BadSignature:
        return False


@bp.get("/login")
def login_form():
    if g.user:
        return redirect(url_for("docs.list_docs"))
    return render_template("login.html", token=_login_token(), error=None)


@bp.post("/login")
def login_submit():
    cfg = current_app.config
    if not _login_token_ok(request.form.get("login_token", "")):
        return render_template("login.html", token=_login_token(), error="Reload the page and try again."), 400
    email = request.form.get("email", "").strip().lower()[:254]
    password = request.form.get("password", "")[:200]
    u = db.one("SELECT * FROM users WHERE email = %s", (email,))
    locked = bool(u and db.one("SELECT 1 AS x FROM users WHERE id=%s AND locked_until > now()", (u["id"],)))
    good = check_password_hash(u["password_hash"] if u else DUMMY_HASH, password)
    if not (u and good and u["active"] and not locked):
        if u:
            db.run("""UPDATE users SET failed_logins = failed_logins + 1,
                         locked_until = CASE WHEN failed_logins + 1 >= %s
                                        THEN now() + make_interval(mins => %s) ELSE locked_until END
                       WHERE id = %s""", (cfg["MAX_FAILED_LOGINS"], cfg["LOCKOUT_MINUTES"], u["id"]))
            db.conn().commit()
        audit("login", "denied", actor=None, email=email,
              reason="locked" if locked else ("disabled" if u and not u["active"] else "bad_credentials"))
        return render_template("login.html", token=_login_token(),
                               error="Email or password is wrong, or the account is locked."), 401
    db.run("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s", (u["id"],))
    old = request.cookies.get(auth.COOKIE)
    if old:                                                  # new session id on every login
        db.run("DELETE FROM sessions WHERE id = %s", (auth.token_hash(old),))
    tok = auth.create_session(u["id"])
    audit("login", "allowed", actor={"id": u["id"], "email": u["email"]})
    resp = redirect(url_for("docs.list_docs"))
    resp.set_cookie(auth.COOKIE, tok, httponly=True, secure=cfg["COOKIE_SECURE"], samesite="Lax",
                    max_age=cfg["SESSION_MAX_HOURS"] * 3600)
    return resp


@bp.post("/logout")
def logout():
    db.run("DELETE FROM sessions WHERE id = %s", (g.session["id"],))
    audit("logout", "allowed", actor=g.user)
    resp = make_response(redirect(url_for("auth.login_form")))
    resp.delete_cookie(auth.COOKIE)
    return resp


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("docs.list_docs"))

    if request.method == "GET":
        return render_template("login.html", register_mode=True, token=_reg_token(), error=None, success=None)

    token = request.form.get("token") or request.form.get("csrf_token") or request.form.get("login_token") or ""
    if not _reg_token_ok(token):
        audit("register", "denied", actor=None, reason="invalid_csrf_token")
        return render_template("login.html", register_mode=True, token=_reg_token(),
                               error="Session expired or invalid token. Please try again."), 400

    email = request.form.get("email", "").strip().lower()[:254]
    password = request.form.get("password", "")[:200]
    role = request.form.get("role", "owner").strip().lower()

    if not email or "@" not in email or len(email) < 5 or "." not in email.split("@")[-1]:
        audit("register", "denied", actor=None, email=email, reason="invalid_email")
        return render_template("login.html", register_mode=True, token=_reg_token(),
                               error="Please provide a valid email address."), 400

    # Never allow public registration as admin
    if role not in ("owner", "viewer"):
        audit("register", "denied", actor=None, email=email, reason="disallowed_role", requested_role=role)
        return render_template("login.html", register_mode=True, token=_reg_token(),
                               error="Invalid role selected. Only owner and viewer accounts can be registered."), 400

    if not password or len(password) < 12:
        audit("register", "denied", actor=None, email=email, reason="password_too_short")
        return render_template("login.html", register_mode=True, token=_reg_token(),
                               error="Password must be at least 12 characters."), 400

    existing = db.one("SELECT id FROM users WHERE email = %s", (email,))
    if existing:
        audit("register", "denied", actor=None, email=email, reason="duplicate_email")
        return render_template("login.html", register_mode=True, token=_reg_token(),
                               error="An account with that email already exists."), 400

    try:
        u = create_user(email, password, role)
        db.conn().commit()
        audit("register", "allowed", actor=None, target_user_id=u["id"], email=email, role=role)
        return render_template("login.html", token=_login_token(),
                               success="Account created successfully! You can now sign in.")
    except ValueError as ve:
        db.conn().rollback()
        audit("register", "denied", actor=None, email=email, reason=str(ve))
        return render_template("login.html", register_mode=True, token=_reg_token(),
                               error=str(ve)), 400
    except Exception:
        db.conn().rollback()
        audit("register", "denied", actor=None, email=email, reason="db_error")
        return render_template("login.html", register_mode=True, token=_reg_token(),
                               error="Could not create account. Please try again later."), 400
