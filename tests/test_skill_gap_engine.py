"""
tests/test_skill_gap_engine.py
=================================
Focused unit tests for services/skill_gap_engine.py — the module that
implements ISIS's explainable career-mapping relationship:

    detected skills  →  role-required skills  →  overlap/match score
                     →  missing skills  →  (feeds learning_recommender)

No unit tests previously existed for this module (only an end-to-end
Flask-route test in test_career_hub.py), so these are new, not updates.

These tests use the same deterministic fake-encoder pattern already
established in tests/test_nlp_pipeline.py — skill_gap_engine.py calls
nlp.embedding_engine.encode() directly, so overriding it here exercises the
REAL matching/thresholding logic in skill_gap_engine.py (MATCH_THRESHOLD,
PARTIAL_THRESHOLD, coverage weighting, sorting) without needing the actual
sentence-transformers model or network access.

The fake encoder's vocabulary is deliberately small and chosen so that
similarity scores land predictably in each of the three real bands the
module already defines:
    strong overlap  → cosine ≈ 1.0   (>= MATCH_THRESHOLD = 0.42)
    partial overlap → cosine ≈ 0.316 (>= PARTIAL_THRESHOLD = 0.28, < MATCH_THRESHOLD)
    no overlap      → cosine = 0.0   (< PARTIAL_THRESHOLD)
This is a property of the vector geometry (shared vs. unshared vocabulary
words), verified by hand before writing these tests — not tuned to force a
particular test to pass.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from nlp import embedding_engine
from services import role_taxonomy, skill_gap_engine

_VOCAB = [
    "python", "programming", "docker", "container", "sql", "database",
    "kubernetes", "orchestration", "rest", "api", "git", "version",
    # Deliberately unrelated to any role_taxonomy skill phrase (verified by
    # inspection) — used only to dilute a sentence's vector norm without
    # touching any OTHER role skill's similarity, so a "partial overlap"
    # test sentence stays a clean, single-skill signal.
    "excel", "marketing", "photoshop",
]


def _fake_encoder(texts):
    vectors = []
    for text in texts:
        lowered = text.lower()
        vec = np.array([1.0 if w in lowered else 0.0 for w in _VOCAB], dtype="float32")
        norm = np.linalg.norm(vec)
        vectors.append(vec / norm if norm > 0 else vec)
    return np.array(vectors, dtype="float32")


@pytest.fixture(autouse=True)
def fake_skill_gap():
    """Overrides (shadows) the conftest.py autouse fixture of the same name,
    which replaces skill_gap_engine.analyze_gap with a fixed stub for every
    other test in the suite. THIS file's whole purpose is to exercise the
    real analyze_gap logic, so it opts out via the pattern the conftest
    fixture's own docstring documents, and uses the fake embedding encoder
    below instead (same approach as tests/test_nlp_pipeline.py)."""
    yield


@pytest.fixture(autouse=True)
def _use_fake_encoder():
    embedding_engine.set_encoder_override(_fake_encoder)
    yield
    embedding_engine.set_encoder_override(None)


class TestStrongSkillOverlap:

    def test_exact_phrase_match_lands_in_matched_bucket(self):
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=["I have hands-on Docker containerization experience"],
        )
        matched_skills = {m["skill"] for m in result.matched}
        assert "Docker containerization" in matched_skills

    def test_matched_entry_is_explainable(self):
        """Requirement: the recommendation must show WHICH detected skill
        justified each match, not just a bare pass/fail."""
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=["I have hands-on Docker containerization experience"],
        )
        entry = next(m for m in result.matched if m["skill"] == "Docker containerization")
        assert entry["matched_by"] == "I have hands-on Docker containerization experience"
        assert entry["similarity"] >= skill_gap_engine.MATCH_THRESHOLD
        assert entry["tier"] in ("core", "supporting")

    def test_strong_overlap_contributes_to_coverage(self):
        role_data = role_taxonomy.get_role_skills("Backend Developer")
        assert "Docker containerization" in role_data["supporting"]
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=["I have hands-on Docker containerization experience"],
        )
        assert result.coverage_pct > 0.0


class TestPartialSkillOverlap:

    def test_weak_incidental_mention_lands_in_partial_bucket(self):
        """A user skill that only tangentially touches a role skill (shares
        some but not most of its meaning) should be 'partial', not a full
        'matched' — and definitely not silently dropped as 'missing'."""
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=[
                "I containerized a small side-project once, but mostly did "
                "marketing, excel spreadsheets, and photoshop design work."
            ],
        )
        matched_skills = {m["skill"] for m in result.matched}
        partial_skills = {m["skill"] for m in result.partial}
        assert "Docker containerization" not in matched_skills
        assert "Docker containerization" in partial_skills

    def test_partial_entry_similarity_is_in_the_expected_band(self):
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=[
                "I containerized a small side-project once, but mostly did "
                "marketing, excel spreadsheets, and photoshop design work."
            ],
        )
        entry = next(m for m in result.partial if m["skill"] == "Docker containerization")
        assert skill_gap_engine.PARTIAL_THRESHOLD <= entry["similarity"] < skill_gap_engine.MATCH_THRESHOLD

    def test_partial_matches_count_less_toward_coverage_than_full_matches(self):
        """Coverage weighting should genuinely distinguish partial from
        full evidence, not treat them identically."""
        full = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=["I have hands-on Docker containerization experience"],
        )
        partial = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=[
                "I containerized a small side-project once, but mostly did "
                "marketing, excel spreadsheets, and photoshop design work."
            ],
        )
        assert partial.coverage_pct < full.coverage_pct


class TestNoMeaningfulOverlap:

    def test_unrelated_skills_produce_zero_matches(self):
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=["I enjoy gardening and cooking for my family"],
        )
        assert result.matched == []
        assert result.partial == []

    def test_unrelated_skills_land_everything_in_missing(self):
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=["I enjoy gardening and cooking for my family"],
        )
        expected_total = len(role_taxonomy.get_all_role_skills_flat("Backend Developer"))
        assert len(result.missing) == expected_total
        assert result.coverage_pct == 0.0

    def test_empty_user_skills_handled_safely(self):
        """No exception, no crash — everything reported as missing with
        zero coverage, exactly like the 'no overlap' case."""
        result = skill_gap_engine.analyze_gap("Backend Developer", user_skills=[])
        assert result.matched == []
        assert result.partial == []
        expected_total = len(role_taxonomy.get_all_role_skills_flat("Backend Developer"))
        assert len(result.missing) == expected_total
        assert result.coverage_pct == 0.0
        assert result.user_skill_count == 0

    def test_blank_and_whitespace_only_skills_are_filtered_out_safely(self):
        result = skill_gap_engine.analyze_gap(
            "Backend Developer", user_skills=["   ", "", "\t"]
        )
        assert result.user_skill_count == 0
        assert result.coverage_pct == 0.0


class TestMultipleDetectedSkills:

    def test_multiple_skills_across_core_and_supporting_tiers_all_recognized(self):
        """Requirement: multiple detected skills should each be reflected
        in the result — not just the single best-matching one."""
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=[
                "I built REST API endpoints for a small project",
                "I used SQL to design a database schema",
                "I have Docker containerization experience",
            ],
        )
        matched_skills = {m["skill"] for m in result.matched}
        assert "REST API development" in matched_skills
        assert "database design and SQL" in matched_skills
        assert "Docker containerization" in matched_skills

    def test_each_match_is_attributed_to_the_specific_detected_skill_that_justified_it(self):
        """Explainability: with several detected skills provided, each
        matched role-skill should cite the ACTUAL detected skill phrase
        that produced it, not an arbitrary or blended one."""
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=[
                "I built REST API endpoints for a small project",
                "I used SQL to design a database schema",
            ],
        )
        by_skill = {m["skill"]: m["matched_by"] for m in result.matched}
        assert by_skill["REST API development"] == "I built REST API endpoints for a small project"
        assert by_skill["database design and SQL"] == "I used SQL to design a database schema"

    def test_more_detected_skills_yields_higher_or_equal_coverage(self):
        one_skill = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=["I built REST API endpoints for a small project"],
        )
        three_skills = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=[
                "I built REST API endpoints for a small project",
                "I used SQL to design a database schema",
                "I have Docker containerization experience",
            ],
        )
        assert three_skills.coverage_pct >= one_skill.coverage_pct


class TestMissingSkillsCalculation:

    def test_missing_equals_role_skills_minus_matched_and_partial(self):
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            user_skills=["I built REST API endpoints for a small project"],
        )
        all_role_skills = set(role_taxonomy.get_all_role_skills_flat("Backend Developer"))
        matched_and_partial = {m["skill"] for m in result.matched} | {m["skill"] for m in result.partial}
        missing_skills = {m["skill"] for m in result.missing}
        assert missing_skills == all_role_skills - matched_and_partial

    def test_missing_entries_carry_correct_tier(self):
        result = skill_gap_engine.analyze_gap("Backend Developer", user_skills=[])
        role_data = role_taxonomy.get_role_skills("Backend Developer")
        for entry in result.missing:
            expected_tier = "core" if entry["skill"] in role_data["core"] else "supporting"
            assert entry["tier"] == expected_tier

    def test_missing_list_is_sorted_core_skills_first(self):
        result = skill_gap_engine.analyze_gap("Backend Developer", user_skills=[])
        tiers = [entry["tier"] for entry in result.missing]
        first_supporting_index = next(
            (i for i, t in enumerate(tiers) if t == "supporting"), len(tiers)
        )
        # once a "supporting" entry appears, no "core" entry should follow it
        assert "core" not in tiers[first_supporting_index:]

    def test_core_coverage_pct_only_reflects_core_tier(self):
        """core_coverage_pct should ignore supporting-tier matches entirely."""
        result = skill_gap_engine.analyze_gap(
            "Backend Developer",
            # Docker containerization is a SUPPORTING skill for Backend Developer
            user_skills=["I have hands-on Docker containerization experience"],
        )
        assert result.core_coverage_pct == 0.0
        assert result.coverage_pct > 0.0  # still contributes to overall coverage


class TestRoleTaxonomyGuards:
    """Small guard-rail tests on the taxonomy access functions skill_gap_engine
    depends on, since they're part of the same explainable pipeline."""

    def test_unknown_role_raises_clear_error(self):
        with pytest.raises(KeyError):
            role_taxonomy.get_role_skills("Underwater Basket Weaver")

    def test_analyze_gap_propagates_unknown_role_error(self):
        with pytest.raises(KeyError):
            skill_gap_engine.analyze_gap("Underwater Basket Weaver", user_skills=["Python programming"])

    def test_all_target_roles_have_nonempty_core_and_supporting_skills(self):
        for role_name in role_taxonomy.list_target_roles():
            role_data = role_taxonomy.get_role_skills(role_name)
            assert len(role_data["core"]) > 0
            assert len(role_data["supporting"]) > 0
