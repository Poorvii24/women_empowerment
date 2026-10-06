"""
tests/test_history.py
======================
The History page (past logged activities).
"""


class TestHistory:
    def test_history_page_loads_empty(self, auth_client):
        resp = auth_client.get("/history")
        assert resp.status_code == 200

    def test_history_page_shows_logged_activity(self, auth_client, app_module, test_user):
        app_module.db.insert_activity(
            user_id=str(test_user["id"]),
            input_activity="Organized a community fundraiser",
            mapped_skill="Event Coordination",
            onet_category="Administrative",
            leadership_category="Leadership",
            skill_magnitude=70,
            market_value="High",
            career_equivalency="Matches Event Coordinator",
            leadership_index=65,
            employability_score=70,
            skills_mapped=["Event Coordination"],
            resume_snippet="Coordinated a community fundraiser end to end.",
        )
        resp = auth_client.get("/history")
        assert resp.status_code == 200
        assert b"Event Coordination" in resp.data or b"fundraiser" in resp.data.lower()
