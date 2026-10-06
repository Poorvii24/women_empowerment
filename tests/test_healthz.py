"""
tests/test_healthz.py
======================
Unauthenticated liveness/readiness endpoint used by Docker HEALTHCHECK,
CI startup verification, and load balancers.
"""


class TestHealthz:
    def test_healthz_does_not_require_login(self, app_module):
        client = app_module.app.test_client()
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_healthz_reports_database_ok(self, app_module):
        client = app_module.app.test_client()
        resp = client.get("/healthz")
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["database"] == "ok"
        assert "gemini_configured" in data
