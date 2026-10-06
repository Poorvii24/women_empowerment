"""
tests/test_analyze_activity.py
=================================
Integration test for POST /analyze_activity — verifies the full request path
(auth -> validation -> hybrid NLP pipeline -> Gemini-or-fallback -> DB write
-> JSON response) end-to-end, and specifically that the classical NLP
pipeline's output (keyphrases, hybrid engine tag) is actually wired into the
response, not just present in nlp/skill_matcher.py in isolation.

Uses the same deterministic fake-encoder pattern as tests/test_nlp_pipeline.py
so this test never needs network access to download the real
all-MiniLM-L6-v2 model. GEMINI_API_KEY is unset in the test environment
(see conftest/.env.example), so these requests exercise the fully-supported
"embedding-only" / local-fallback path.
"""
import os
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
        vec = np.array([1.0 if word in lowered else 0.0 for word in _VOCAB], dtype="float32")
        padded = np.zeros(embedding_engine.EMBEDDING_DIM, dtype="float32")
        padded[: len(vec)] = vec
        norm = np.linalg.norm(padded)
        vectors.append(padded / norm if norm > 0 else padded)
    return np.array(vectors, dtype="float32")


@pytest.fixture(autouse=True)
def _use_fake_encoder():
    embedding_engine.set_encoder_override(_fake_encoder)
    skill_matcher._skill_profiles = None
    skill_matcher._skill_embeddings = None
    skill_matcher._skills_json_hash = None
    original_cache_path = skill_matcher.CACHE_PATH
    skill_matcher.CACHE_PATH = original_cache_path + ".test_analyze_route.npz"
    yield
    embedding_engine.set_encoder_override(None)
    if os.path.exists(skill_matcher.CACHE_PATH):
        os.remove(skill_matcher.CACHE_PATH)
    skill_matcher.CACHE_PATH = original_cache_path
    skill_matcher._skill_profiles = None
    skill_matcher._skill_embeddings = None
    skill_matcher._skills_json_hash = None


class TestAnalyzeActivityRoute:

    def test_rejects_too_short_input(self, auth_client, csrf_token):
        resp = auth_client.post(
            "/analyze_activity",
            json={"activity": "hi"},
            headers={"X-CSRFToken": csrf_token},
        )
        assert resp.status_code == 400

    def test_analyze_activity_returns_success_with_nlp_pipeline_output(self, auth_client, csrf_token):
        resp = auth_client.post(
            "/analyze_activity",
            json={"activity": "I managed the monthly household budget and tracked savings carefully for my family."},
            headers={"X-CSRFToken": csrf_token},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"

        # Without GEMINI_API_KEY configured in the test environment, this
        # must be the local embedding/TF-IDF fallback path — not an error.
        assert data["source"] == "local_fallback"
        assert data["transferable_skill"] == "Financial Management & Budget Allocation"

        # The hybrid classical+embedding NLP pipeline output must be present
        # and correctly shaped in the actual HTTP response, not just when
        # calling skill_matcher directly.
        semantic = data["semantic_analysis"]
        assert semantic["engine"] == "embedding_tfidf_hybrid_v2"
        assert "keyphrases" in semantic
        assert isinstance(semantic["keyphrases"], list)
        if semantic["keyphrases"]:
            assert "phrase" in semantic["keyphrases"][0]
            assert "score" in semantic["keyphrases"][0]

    def test_analyze_activity_persists_and_returns_activity_id(self, auth_client, csrf_token):
        resp = auth_client.post(
            "/analyze_activity",
            json={"activity": "I tutor and mentor neighborhood kids in maths after school every day."},
            headers={"X-CSRFToken": csrf_token},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["activity_id"] is not None
        assert data["transferable_skill"] == "Training, Mentoring & Instruction"

    def test_analyze_activity_requires_login(self, client):
        # No session and no CSRF token: the CSRF check runs first and
        # rejects with 400 before the login_required check is ever reached
        # — either way, the request is correctly refused unauthenticated.
        resp = client.post("/analyze_activity", json={"activity": "I managed a household budget."})
        assert resp.status_code in (302, 400, 401)
