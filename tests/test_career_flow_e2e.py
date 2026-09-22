"""
tests/test_career_flow_e2e.py
================================
End-to-end validation of the REAL Flask/API career flow — actual HTTP
requests against the actual routes, not direct module calls.

This complements, and deliberately does not duplicate, existing coverage:
  - tests/test_analyze_activity.py already covers POST /analyze_activity in
    isolation (validation, NLP output shape, local-fallback source, auth).
  - tests/test_career_hub.py already covers /career/set_target and resume
    upload in isolation, and has two thin /career/analysis smoke checks.
  - tests/test_pipeline_integration.py already validates the pipeline
    end-to-end at the MODULE level (calling skill_matcher/skill_gap_engine/
    learning_recommender functions directly).

What was missing, and what this file adds: whether the pipeline holds
together across REAL HTTP requests and REAL database persistence — i.e.
log an activity via POST, reload the app state via a fresh GET (simulating
navigation/page reload), and confirm /career/analysis reflects exactly what
was actually written to the database, with the full response structure the
frontend depends on, empty/invalid input handled without a 500, and no
external AI dependency on the analysis endpoint itself.

Uses the same deterministic fake-encoder pattern as the rest of the suite —
no network access or real sentence-transformers model required.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from nlp import embedding_engine, skill_matcher

_VOCAB = [
    "budget", "finance", "money", "savings",
    "teach", "tutor", "mentor", "educat",
    "lead", "supervis", "team", "motivat",
    "cook", "meal", "nutrition", "food",
    "care", "health", "patient", "elder",
]


def _fake_encoder(texts):
    vectors = []
    for text in texts:
        lowered = text.lower()
        vec = np.array([1.0 if w in lowered else 0.0 for w in _VOCAB], dtype="float32")
        padded = np.zeros(embedding_engine.EMBEDDING_DIM, dtype="float32")
        padded[: len(vec)] = vec
        norm = np.linalg.norm(padded)
        vectors.append(padded / norm if norm > 0 else padded)
    return np.array(vectors, dtype="float32")


@pytest.fixture(autouse=True)
def fake_skill_gap():
    """Shadows conftest.py's autouse stub of skill_gap_engine.analyze_gap —
    this file's whole purpose is to exercise the real career-mapping logic
    through real HTTP requests, not a fixed stub response."""
    yield


@pytest.fixture(autouse=True)
def _use_fake_encoder():
    embedding_engine.set_encoder_override(_fake_encoder)
    skill_matcher._skill_profiles = None
    skill_matcher._skill_embeddings = None
    skill_matcher._skills_json_hash = None
    original_cache_path = skill_matcher.CACHE_PATH
    skill_matcher.CACHE_PATH = original_cache_path + ".test_career_flow_e2e.npz"
    yield
    embedding_engine.set_encoder_override(None)
    if os.path.exists(skill_matcher.CACHE_PATH):
        os.remove(skill_matcher.CACHE_PATH)
    skill_matcher.CACHE_PATH = original_cache_path
    skill_matcher._skill_profiles = None
    skill_matcher._skill_embeddings = None
    skill_matcher._skills_json_hash = None


def _csrf_from(resp):
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    if match:
        return match.group(1)
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1) if match else None


class TestFullAuthenticatedCareerFlow:
    """One continuous session: log in (via the auth_client fixture) -> log
    an activity -> set a target role -> read back the full analysis. Each
    step's output is checked against what the NEXT step actually needs,
    not just its own status code."""

    def test_activity_then_target_role_then_analysis(self, auth_client, csrf_token, app_module, test_user):
        # Step 1: log a real activity through the real route.
        activity_resp = auth_client.post(
            "/analyze_activity",
            json={"activity": "I managed the monthly household budget and tracked savings carefully."},
            headers={"X-CSRFToken": csrf_token},
        )
        assert activity_resp.status_code == 201
        assert activity_resp.get_json()["transferable_skill"] == "Financial Management & Budget Allocation"

        # Step 2: set a target role through the real route.
        page = auth_client.get("/career")
        token = _csrf_from(page)
        auth_client.post(
            "/career/set_target",
            data={"target_role": "Backend Developer", "csrf_token": token},
            follow_redirects=True,
        )
        assert app_module.db.get_user_target_role(str(test_user["id"])) == "Backend Developer"

        # Step 3: read the analysis back through the real route.
        analysis_resp = auth_client.get("/career/analysis")
        assert analysis_resp.status_code == 200
        data = analysis_resp.get_json()
        assert data["status"] == "ok"
        assert data["target_role"] == "Backend Developer"
        # The logged activity's confidently-detected skill must be visible
        # somewhere in the gap (not necessarily "matched" against this
        # unrelated technical role, but the user_skill_count must reflect it).
        assert data["gap"]["user_skill_count"] >= 1

    def test_response_structure_matches_what_the_frontend_reads(self, auth_client, csrf_token, app_module, test_user):
        """Pins the JSON contract app.py documents — every top-level key the
        career.html JS actually consumes must be present with the right shape."""
        page = auth_client.get("/career")
        token = _csrf_from(page)
        auth_client.post(
            "/career/set_target",
            data={"target_role": "Backend Developer", "csrf_token": token},
            follow_redirects=True,
        )
        data = auth_client.get("/career/analysis").get_json()

        assert data["status"] == "ok"
        assert set(data["gap"].keys()) == {
            "matched", "partial", "missing", "coverage_pct", "core_coverage_pct", "user_skill_count",
        }
        assert isinstance(data["gap"]["matched"], list)
        assert set(data["score"].keys()) >= {
            "overall", "technical", "leadership", "communication",
            "consistency", "growth", "explanations", "axis_details",
        }
        assert set(data["learning_plan"].keys()) == {"day_30", "day_60", "day_90"}
        assert "ats" in data and "recruiter" in data
        assert "growth" in data
        assert isinstance(data["resume_uploaded"], bool)


class TestNlpToCareerMappingChainOverRealHttp:
    """The specific chain this task calls out: NLP -> career mapping ->
    skill gap -> learning plan, exercised end to end through real requests
    and a real database round-trip (not a direct function call)."""

    def test_confident_nlp_skill_persists_and_flows_into_the_gap(self, auth_client, csrf_token, app_module, test_user):
        auth_client.post(
            "/analyze_activity",
            json={"activity": "I tutor and mentor neighborhood kids in maths after school every day."},
            headers={"X-CSRFToken": csrf_token},
        )
        # Confirm it was actually written to the database, not just
        # returned in the HTTP response.
        activities = app_module.db.get_user_activities(str(test_user["id"]))
        assert len(activities) == 1
        assert activities[0]["nlp_primary_skill"] == "Training, Mentoring & Instruction"
        assert activities[0]["nlp_confidence_pct"] > 0

        token = _csrf_from(auth_client.get("/career"))
        auth_client.post(
            "/career/set_target",
            data={"target_role": "Backend Developer", "csrf_token": token},
            follow_redirects=True,
        )
        data = auth_client.get("/career/analysis").get_json()
        assert data["gap"]["user_skill_count"] >= 1
        # the learning plan must be well-formed and non-empty for a role
        # this far from the detected skill
        assert len(data["learning_plan"]["day_30"]) > 0

    def test_irrelevant_activity_does_not_leak_a_placeholder_skill_via_http(
        self, auth_client, csrf_token, app_module, test_user
    ):
        """Route-level regression guard for the placeholder-leak bug: when
        the NLP stage confidently detects NOTHING, /career/analysis must not
        report a detected skill anyway. (test_pipeline_integration.py
        already checks this at the module level; this is the same
        invariant checked through the real HTTP + DB path.)"""
        auth_client.post(
            "/analyze_activity",
            json={"activity": "The sky was cloudy, the traffic was slow, and the coffee was cold."},
            headers={"X-CSRFToken": csrf_token},
        )
        activities = app_module.db.get_user_activities(str(test_user["id"]))
        assert activities[0]["nlp_confidence_pct"] == 0

        token = _csrf_from(auth_client.get("/career"))
        auth_client.post(
            "/career/set_target",
            data={"target_role": "Backend Developer", "csrf_token": token},
            follow_redirects=True,
        )
        data = auth_client.get("/career/analysis").get_json()
        assert data["gap"]["user_skill_count"] == 0
        assert data["gap"]["coverage_pct"] == 0.0

    def test_reload_after_activity_reflects_persisted_state_not_request_local_state(
        self, auth_client, csrf_token, app_module, test_user
    ):
        """Simulates closing and reopening the page: a completely separate
        GET request must see what was persisted by an earlier POST."""
        auth_client.post(
            "/analyze_activity",
            json={"activity": "I managed the monthly household budget and tracked savings carefully."},
            headers={"X-CSRFToken": csrf_token},
        )
        token = _csrf_from(auth_client.get("/career"))
        auth_client.post(
            "/career/set_target",
            data={"target_role": "Backend Developer", "csrf_token": token},
            follow_redirects=True,
        )

        first_read = auth_client.get("/career/analysis").get_json()
        second_read = auth_client.get("/career/analysis").get_json()
        assert first_read["gap"]["user_skill_count"] == second_read["gap"]["user_skill_count"]
        assert first_read["gap"]["coverage_pct"] == second_read["gap"]["coverage_pct"]


class TestEmptyAndInvalidInputHandling:

    def test_analysis_before_any_target_role_is_set(self, auth_client):
        resp = auth_client.get("/career/analysis")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "no_target"

    def test_analysis_with_target_role_but_zero_activities_and_no_resume(
        self, auth_client, app_module, test_user
    ):
        """A brand-new user with a goal but nothing else yet: everything
        should come back as a clean, fully-missing gap — no crash."""
        token = _csrf_from(auth_client.get("/career"))
        auth_client.post(
            "/career/set_target",
            data={"target_role": "Backend Developer", "csrf_token": token},
            follow_redirects=True,
        )
        data = auth_client.get("/career/analysis").get_json()
        assert data["status"] == "ok"
        assert data["gap"]["user_skill_count"] == 0
        assert data["gap"]["coverage_pct"] == 0.0
        assert data["resume_uploaded"] is False

    def test_empty_activity_text_rejected_not_500(self, auth_client, csrf_token):
        resp = auth_client.post(
            "/analyze_activity",
            json={"activity": ""},
            headers={"X-CSRFToken": csrf_token},
        )
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_missing_activity_field_rejected_not_500(self, auth_client, csrf_token):
        resp = auth_client.post(
            "/analyze_activity",
            json={},
            headers={"X-CSRFToken": csrf_token},
        )
        assert resp.status_code == 400

    def test_set_target_with_blank_role_does_not_crash_analysis(self, auth_client, app_module, test_user):
        token = _csrf_from(auth_client.get("/career"))
        auth_client.post(
            "/career/set_target",
            data={"target_role": "", "csrf_token": token},
            follow_redirects=True,
        )
        assert app_module.db.get_user_target_role(str(test_user["id"])) is None
        resp = auth_client.get("/career/analysis")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "no_target"


class TestGracefulFallbackWithoutExternalAI:
    """GEMINI_API_KEY is unset throughout this test session (see
    conftest/.env.example) — every request here already exercises the
    no-external-AI path for real, rather than mocking it."""

    def test_analyze_activity_falls_back_locally_without_gemini(self, auth_client, csrf_token):
        resp = auth_client.post(
            "/analyze_activity",
            json={"activity": "I cook meals every day for a family of six."},
            headers={"X-CSRFToken": csrf_token},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["source"] == "local_fallback"
        assert data["transferable_skill"]  # a real skill name, not empty/error

    def test_career_analysis_has_no_external_ai_dependency(self, auth_client, app_module, test_user):
        """/career/analysis is built entirely from local, deterministic
        services (skill_gap_engine, scoring_engine, learning_recommender,
        opportunity_recommender, growth_tracker, ats_engine) — it must
        succeed fully with no AI client configured at all, not merely
        degrade gracefully."""
        token = _csrf_from(auth_client.get("/career"))
        auth_client.post(
            "/career/set_target",
            data={"target_role": "Data Scientist", "csrf_token": token},
            follow_redirects=True,
        )
        resp = auth_client.get("/career/analysis")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "error" not in data
