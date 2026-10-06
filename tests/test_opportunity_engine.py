"""
tests/test_opportunity_engine.py
=================================
The Opportunity Engine has two parts in this codebase:
  1. Notifications (db.add_notification / the /notifications routes) —
     alerts surfaced to the user as they log activities.
  2. services/opportunity_recommender.py — project/hackathon/certification/
     open-source recommendations used by both PDFs, the Career Snapshot,
     and the AI Copilot.
"""

from services import opportunity_recommender


class TestNotificationEndpoints:
    def test_notifications_count_zero_for_new_user(self, auth_client):
        resp = auth_client.get("/notifications/count")
        assert resp.status_code == 200
        assert resp.get_json()["unread_count"] == 0

    def test_notifications_list_reflects_added_notification(self, auth_client, app_module, test_user):
        app_module.db.add_notification(user_id=str(test_user["id"]), message="Test opportunity alert", link="/")

        # Check the unread count BEFORE fetching the list — GET /notifications
        # marks everything read as a side effect, so order matters here.
        count_resp = auth_client.get("/notifications/count")
        assert count_resp.get_json()["unread_count"] == 1

        resp = auth_client.get("/notifications")
        assert resp.status_code == 200
        data = resp.get_json()
        assert any("Test opportunity alert" in n["message"] for n in data["notifications"])

    def test_mark_all_read_clears_count(self, auth_client, app_module, test_user):
        import re

        app_module.db.add_notification(user_id=str(test_user["id"]), message="Another alert", link="/")
        token_resp = auth_client.get("/career")
        token = re.search(r'name="csrf-token" content="([^"]+)"', token_resp.get_data(as_text=True)).group(1)
        auth_client.post("/notifications/mark_read", headers={"X-CSRFToken": token})
        resp = auth_client.get("/notifications/count")
        assert resp.get_json()["unread_count"] == 0


class TestOpportunityRecommender:
    def test_returns_all_expected_categories(self):
        opps = opportunity_recommender.get_opportunities(
            "Data Scientist",
            [
                {"skill": "SQL", "tier": "core"},
                {"skill": "A/B Testing", "tier": "core"},
            ],
        )
        assert set(opps.keys()) >= {"projects", "hackathons", "certifications", "open_source"}

    def test_handles_unknown_role_gracefully(self):
        """Should degrade gracefully rather than crash for a role outside
        the known taxonomy."""
        opps = opportunity_recommender.get_opportunities("Not A Real Role", [])
        assert isinstance(opps, dict)

    def test_handles_no_missing_skills(self):
        opps = opportunity_recommender.get_opportunities("Data Scientist", [])
        assert isinstance(opps, dict)
