"""
tests/test_auth.py
===================
Registration, login, and logout — the entry point for every other workflow.

Every POST fetches a real CSRF token first, matching the app's actual forms
exactly (see register.html / login.html's hidden csrf_token input) — tests
that skip this would silently "pass" by hitting the CSRF-failure redirect
instead of exercising the real registration/login logic.
"""

import re


def get_csrf_from(resp):
    text = resp.get_data(as_text=True)
    match = re.search(r'name="csrf-token" content="([^"]+)"', text)
    if match:
        return match.group(1)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', text)
    return match.group(1) if match else None


class TestRegistration:
    def test_register_page_loads(self, app_module):
        client = app_module.app.test_client()
        resp = client.get("/register")
        assert resp.status_code == 200

    def test_register_new_user_succeeds(self, app_module):
        client = app_module.app.test_client()
        token = get_csrf_from(client.get("/register"))
        resp = client.post(
            "/register",
            data={
                "username": "newuser1",
                "password": "Sup3rSecret!",
                "confirm_password": "Sup3rSecret!",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert app_module.db.get_user_by_username("newuser1") is not None

    def test_register_duplicate_username_rejected(self, app_module, test_user):
        client = app_module.app.test_client()
        token = get_csrf_from(client.get("/register"))
        client.post(
            "/register",
            data={
                "username": test_user["username"],
                "password": "Sup3rSecret!",
                "confirm_password": "Sup3rSecret!",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        conn = app_module.db.get_connection()
        count = conn.execute("SELECT COUNT(*) c FROM users WHERE username = ?", (test_user["username"],)).fetchone()[
            "c"
        ]
        conn.close()
        assert count == 1

    def test_register_password_mismatch_rejected(self, app_module):
        client = app_module.app.test_client()
        token = get_csrf_from(client.get("/register"))
        client.post(
            "/register",
            data={
                "username": "mismatcher",
                "password": "Sup3rSecret!",
                "confirm_password": "Different!",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        assert app_module.db.get_user_by_username("mismatcher") is None

    def test_register_missing_csrf_token_rejected(self, app_module):
        """A POST with no CSRF token at all must not create the account —
        this is the CSRF protection actually doing its job."""
        client = app_module.app.test_client()
        client.post(
            "/register",
            data={
                "username": "nocsrfuser",
                "password": "Sup3rSecret!",
                "confirm_password": "Sup3rSecret!",
            },
            follow_redirects=True,
        )
        assert app_module.db.get_user_by_username("nocsrfuser") is None


class TestLogin:
    def test_login_page_loads(self, app_module):
        client = app_module.app.test_client()
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_login_with_valid_credentials_succeeds(self, app_module):
        from werkzeug.security import generate_password_hash

        app_module.user_repository.create("loginuser", generate_password_hash("Sup3rSecret!"))
        client = app_module.app.test_client()
        token = get_csrf_from(client.get("/login"))
        resp = client.post(
            "/login",
            data={"username": "loginuser", "password": "Sup3rSecret!", "csrf_token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" not in resp.headers.get("Location", "")

    def test_login_with_wrong_password_fails(self, app_module):
        from werkzeug.security import generate_password_hash

        app_module.user_repository.create("loginuser2", generate_password_hash("Sup3rSecret!"))
        client = app_module.app.test_client()
        token = get_csrf_from(client.get("/login"))
        resp = client.post(
            "/login",
            data={"username": "loginuser2", "password": "WrongPassword", "csrf_token": token},
            follow_redirects=True,
        )
        assert resp.request.path == "/login"


class TestLogout:
    def test_logout_clears_session(self, auth_client):
        resp = auth_client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        resp2 = auth_client.get("/", follow_redirects=False)
        assert resp2.status_code == 302


class TestAuthGating:
    def test_dashboard_requires_login(self, app_module):
        client = app_module.app.test_client()
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302

    def test_career_hub_requires_login(self, app_module):
        client = app_module.app.test_client()
        resp = client.get("/career", follow_redirects=False)
        assert resp.status_code == 302
