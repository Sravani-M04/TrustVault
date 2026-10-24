# PROMPTS

**Candidate Record of AI Prompts, Mistakes, and Corrections**

---

### 2026-10-23: Incompatible Tech Stack & Run Instructions
- **Asked:** Generate setup and deployment instructions for TrustVault on the EC2 instance.
- **Produced:** The AI generated a Node.js / React / Prisma startup guide (`cd server && npm install`, `npx prisma migrate`).
- **Wrong:** Running these commands on the EC2 instance immediately failed with `-bash: cd: trustvault/server: No such file or directory`. The codebase is actually a Python/Flask, PostgreSQL RDS, and AWS S3 architecture.
- **Did instead:** Preserved the pure Flask/PostgreSQL architecture, set up Python 3.12 virtual environment, and loaded the database schema directly using `psql db/schema.sql` as documented in `commit 6a427e7`.

---

### 2026-10-23: Broken User Self-Registration Endpoint (Inaccessible Behind Default-Deny Gate)
- **Asked:** Implement self-registration endpoint so users can create company workspace accounts.
- **Produced:** Added a `@bp.route("/register")` route in `app/routes/auth_routes.py` and a registration form in `login.html`.
- **Wrong:** The AI failed to register `auth.register` in `app/auth.py`'s `PUBLIC` allowlist. Because the application enforces default-deny via `gate()`, any unauthenticated user requesting `/register` was immediately redirected back to `/login`, making registration completely unreachable.
- **Did instead:** Added `"auth.register"` to `PUBLIC` in `app/auth.py` and updated `tests/test_auth.py` allowlist tests to verify public access (commit `e7c89c7`).

---

### 2026-10-24: CSRF Session Bypass Failure on Unauthenticated Registration POST
- **Asked:** Wire up POST submission for `/register` with CSRF protection.
- **Produced:** The AI attempted to reuse the session-based CSRF token check (`g.session["csrf"]`).
- **Wrong:** Unauthenticated visitors do not have an active session cookie (`g.session` is `None`). Submitting the registration form crashed with an unhandled exception or returned HTTP 400.
- **Did instead:** Implemented timed, signed cryptographic registration tokens via `URLSafeTimedSerializer(SECRET_KEY, salt="register-csrf")` with a 15-minute expiration window (`_reg_token()` and `_reg_token_ok()`). Added test `test_register_without_valid_csrf_token_is_refused`.

---

### 2026-10-24: Nonexistent Method `db.execute` and UUID Data Type Incompatibility
- **Asked:** Implement database insertion logic for new registered users.
- **Produced:** The AI wrote:
  `user_id = str(uuid.uuid4())`
  `db.execute("INSERT INTO users (id, email, password_hash, role, active) VALUES (%s, %s, %s, %s, true)", (user_id, ...))`
- **Wrong:** `app.db` has no method named `execute` (it defines `db.run`, `db.one`, and `db.all_`), throwing an `AttributeError`. Furthermore, `users.id` in `db/schema.sql` is a `SERIAL PRIMARY KEY` (integer), not a UUID, which causes a PostgreSQL type error.
- **Did instead:** Replaced the query with the canonical helper `app.users.create_user(email, password, role)`, which properly hashes passwords using `generate_password_hash`, uses standard integer primary keys, enforces a 12+ character password policy, and commits via `db.conn().commit()`.

---

### 2026-10-24: Unrestricted Public Registration Role Escalation to Admin
- **Asked:** Allow role selection on registration.
- **Produced:** The AI accepted `role = request.form.get("role", "owner").strip()` without role validation.
- **Wrong:** Any unauthenticated user could craft a POST request with `role="admin"`, escalating themselves to a full system administrator.
- **Did instead:** Restricted public registration strictly to non-admin roles `("owner", "viewer")`. Any attempt to register as `admin` is rejected with HTTP 400 and logged to the tamper-evident audit trail with `audit("register", "denied", reason="disallowed_role")`. Verified by test `test_register_admin_role_escalation_is_refused`.

---

### 2026-10-24: Test Client Session Cookie Collision in Authentication Tests
- **Asked:** Run `test_session_cookie_flags` and `test_lockout_after_repeated_failures`.
- **Produced:** Reused the pre-authenticated `alice` fixture to fetch `/login` and parse the CSRF `login_token`.
- **Wrong:** Because `alice` was already authenticated by the fixture, requesting `/login` triggered `if g.user: return redirect(url_for('docs.list_docs'))` (HTTP 302). Regex search for `login_token` failed with `AttributeError: 'NoneType' object has no attribute 'group'`.
- **Did instead:** Updated `Client.login` in `tests/conftest.py` to delete `tv_session` before requesting the login form, and updated `test_session_cookie_flags` to clear cookies or use an unauthenticated test client.
