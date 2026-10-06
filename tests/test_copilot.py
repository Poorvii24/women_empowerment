"""
tests/test_copilot.py
======================
AI Career Copilot: ask/history/clear.
"""

import re


def get_csrf_from(resp):
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1) if match else None


class TestCopilotAsk:
    def test_ask_valid_question_returns_grounded_answer(self, auth_client):
        token = get_csrf_from(auth_client.get("/career"))
        resp = auth_client.post(
            "/copilot/ask", json={"message": "Which skills am I missing?"}, headers={"X-CSRFToken": token}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "answer" in data
        assert data["source"] in ("gemini", "local")

    def test_ask_empty_message_rejected(self, auth_client):
        token = get_csrf_from(auth_client.get("/career"))
        resp = auth_client.post("/copilot/ask", json={"message": ""}, headers={"X-CSRFToken": token})
        assert resp.status_code == 400

    def test_ask_overlong_message_rejected(self, auth_client):
        token = get_csrf_from(auth_client.get("/career"))
        resp = auth_client.post("/copilot/ask", json={"message": "x" * 3000}, headers={"X-CSRFToken": token})
        assert resp.status_code == 400

    def test_ask_persists_to_history(self, auth_client, app_module, test_user):
        token = get_csrf_from(auth_client.get("/career"))
        auth_client.post("/copilot/ask", json={"message": "Explain my ATS score."}, headers={"X-CSRFToken": token})
        history = app_module.db.get_copilot_history(str(test_user["id"]))
        assert len(history) == 2  # one user turn, one assistant turn
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_ask_without_target_role_gives_helpful_answer(self, auth_client):
        """A user with no target role set should get a real, specific
        answer telling them what to do next — not a generic error."""
        token = get_csrf_from(auth_client.get("/career"))
        resp = auth_client.post(
            "/copilot/ask", json={"message": "Which skills am I missing?"}, headers={"X-CSRFToken": token}
        )
        data = resp.get_json()
        assert "target role" in data["answer"].lower() or "career hub" in data["answer"].lower()


class TestCopilotHistory:
    def test_history_empty_for_new_user(self, auth_client):
        resp = auth_client.get("/copilot/history")
        assert resp.status_code == 200
        assert resp.get_json()["history"] == []

    def test_history_reflects_conversation(self, auth_client):
        token = get_csrf_from(auth_client.get("/career"))
        auth_client.post(
            "/copilot/ask", json={"message": "Explain my learning roadmap."}, headers={"X-CSRFToken": token}
        )
        resp = auth_client.get("/copilot/history")
        assert len(resp.get_json()["history"]) == 2


class TestCopilotClear:
    def test_clear_empties_history(self, auth_client):
        token = get_csrf_from(auth_client.get("/career"))
        auth_client.post(
            "/copilot/ask", json={"message": "Am I ready for my target role?"}, headers={"X-CSRFToken": token}
        )
        auth_client.post("/copilot/clear", headers={"X-CSRFToken": token})
        resp = auth_client.get("/copilot/history")
        assert resp.get_json()["history"] == []
