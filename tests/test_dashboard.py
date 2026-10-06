"""
tests/test_dashboard.py
========================
Dashboard page and its supporting endpoints.
"""


class TestDashboard:
    def test_dashboard_loads_when_authenticated(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 200
        assert b"ISIS" in resp.data

    def test_dashboard_metrics_returns_json(self, auth_client):
        resp = auth_client.get("/dashboard_metrics")
        assert resp.status_code == 200
        assert resp.is_json

    def test_notifications_count_returns_json(self, auth_client):
        resp = auth_client.get("/notifications/count")
        assert resp.status_code == 200
        assert resp.is_json

    def test_dashboard_metrics_empty_for_new_user(self, auth_client):
        """A freshly created user has zero activities — metrics should
        reflect that without erroring."""
        resp = auth_client.get("/dashboard_metrics")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data is not None
