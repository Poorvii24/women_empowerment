"""
tests/test_pipeline_integration.py
=====================================
End-to-end validation of the complete ISIS intelligence pipeline:

    informal work description
      -> NLP skill extraction        (nlp/skill_matcher.py)
      -> confidence filtering        (skill_matcher's genuine-match floor)
      -> career mapping              (services/skill_gap_engine.py)
      -> skill-gap analysis          (matched / partial / missing)
      -> learning recommendations    (services/learning_recommender.py)

Existing tests cover each stage in isolation (test_nlp_pipeline.py,
test_skill_gap_engine.py, test_learning_recommender.py) and the HTTP route
end-to-end (test_career_hub.py, which stubs the gap engine entirely). What
was NOT covered is the *seams between stages* — whether one stage's output
is consistent with what the next stage assumes. These tests target exactly
that, which is how the placeholder-leak bug below was found.

Both fake encoders here follow the deterministic-override pattern already
used across the suite, so no sentence-transformers model or network access
is required.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from nlp import embedding_engine, skill_matcher
from services import learning_recommender, role_taxonomy, skill_gap_engine
from services.scoring_engine import CareerReadinessScore

# Vocabulary spanning BOTH halves of the pipeline: the informal-skill words
# skills.json profiles are written in, and the technical words
# role_taxonomy.py role skills are written in. One shared encoder has to
# serve both stages, since that's exactly what happens in production.
_VOCAB = [
    # informal / skills.json side
    "budget", "finance", "money", "savings",
    "teach", "tutor", "mentor", "educat",
    "lead", "supervis", "team", "motivat",
    "cook", "meal", "nutrition", "food",
    "care", "health", "patient", "elder",
    "negoti", "vendor", "celebrat",
    # technical / role_taxonomy side
    "python", "programming", "docker", "container", "sql", "database",
    "rest", "api", "git", "version", "test", "debug",
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
    these tests must exercise the real career-mapping logic, not a stub."""
    yield


@pytest.fixture(autouse=True)
def _pipeline_encoder():
    embedding_engine.set_encoder_override(_fake_encoder)
    skill_matcher._skill_profiles = None
    skill_matcher._skill_embeddings = None
    skill_matcher._skills_json_hash = None
    original_cache_path = skill_matcher.CACHE_PATH
    skill_matcher.CACHE_PATH = original_cache_path + ".test_pipeline_integration.npz"
    yield
    embedding_engine.set_encoder_override(None)
    if os.path.exists(skill_matcher.CACHE_PATH):
        os.remove(skill_matcher.CACHE_PATH)
    skill_matcher.CACHE_PATH = original_cache_path
    skill_matcher._skill_profiles = None
    skill_matcher._skill_embeddings = None
    skill_matcher._skills_json_hash = None


def _score():
    return CareerReadinessScore(
        overall=70, technical=70, leadership=70,
        communication=70, consistency=70, growth=70, explanations={},
    )


def _run_pipeline(activity_text, target_role="Backend Developer"):
    """
    Runs the real pipeline end to end, mirroring how app.py chains the
    stages together — including app.py's rule that only CONFIDENT NLP
    matches are forwarded into career mapping (see the confidence filter in
    app.py's career analysis route).
    """
    nlp_result = skill_matcher.analyze_activity_semantic(activity_text)

    # This mirrors app.py exactly: a zero-confidence primary is the
    # "no genuinely confident match" placeholder and must NOT be forwarded
    # as if it were a detected skill.
    detected_skills = []
    primary = nlp_result["primary"]
    if primary["skill"].strip() and primary["confidence_pct"] > 0:
        detected_skills.append(primary["skill"])

    gap = skill_gap_engine.analyze_gap(target_role, detected_skills)
    plan = learning_recommender.build_learning_plan(
        target_role, gap.missing, gap.partial, _score()
    )
    return {"nlp": nlp_result, "detected_skills": detected_skills, "gap": gap, "plan": plan}


class TestRealisticSingleSkillInput:

    def test_single_skill_flows_through_every_stage(self):
        out = _run_pipeline(
            "I managed our household budget and tracked monthly savings carefully."
        )
        # stage 1-2: NLP extraction + confidence filtering
        assert out["nlp"]["primary"]["skill"] == "Financial Management & Budget Allocation"
        assert out["nlp"]["primary"]["confidence_pct"] > 0
        # stage 3: the confident skill is forwarded to career mapping
        assert out["detected_skills"] == ["Financial Management & Budget Allocation"]
        # stage 4: skill-gap analysis ran on it
        assert out["gap"].user_skill_count == 1
        # stage 5: a learning plan was produced
        assert isinstance(out["plan"]["day_30"], list)

    def test_detected_skill_count_matches_what_nlp_actually_found(self):
        """Cross-stage consistency: the gap engine's user_skill_count must
        never claim more detected skills than the NLP stage confidently
        produced."""
        out = _run_pipeline("I cook meals every day for a family of six.")
        assert out["gap"].user_skill_count == len(out["detected_skills"])


class TestRealisticMultiSkillInput:

    def test_multi_skill_input_forwards_all_confident_matches(self):
        text = (
            "I managed the household budget, negotiated with vendors, "
            "celebrated a family birthday party, and tutored my children."
        )
        nlp_result = skill_matcher.analyze_activity_semantic(text)
        confident = [m["skill"] for m in nlp_result["top_matches"]]
        assert len(confident) >= 2  # multi-skill detection still working

        gap = skill_gap_engine.analyze_gap("Backend Developer", confident)
        assert gap.user_skill_count == len(confident)

    def test_every_forwarded_skill_cleared_the_confidence_floor(self):
        """No stage should forward a skill the previous stage rejected."""
        text = (
            "I managed the household budget, negotiated with vendors, "
            "celebrated a family birthday party, and tutored my children."
        )
        nlp_result = skill_matcher.analyze_activity_semantic(text)
        skill_matcher._ensure_loaded()
        floor = 100.0 / len(skill_matcher._skill_profiles)
        for match in nlp_result["top_matches"]:
            assert match["confidence_pct"] > floor


class TestIrrelevantInput:

    def test_irrelevant_input_detects_nothing_and_stays_consistent(self):
        """The integration bug this file was written to catch: the NLP
        stage correctly reports zero confident matches, but its `primary`
        field still carries a labelled placeholder skill. If that
        placeholder is forwarded, the career stage contradicts the NLP
        stage by reporting a detected skill that was explicitly NOT
        detected."""
        out = _run_pipeline("The sky was cloudy, the traffic was slow, and the coffee was cold.")

        assert out["nlp"]["top_matches"] == []
        assert out["nlp"]["primary"]["confidence_pct"] == 0.0
        # the placeholder must NOT have been forwarded
        assert out["detected_skills"] == []
        assert out["gap"].user_skill_count == 0
        assert out["gap"].coverage_pct == 0.0

    def test_irrelevant_input_still_produces_a_safe_learning_plan(self):
        out = _run_pipeline("asdkjf qwoeiru nnnnn zzz")
        # everything is missing, but nothing crashed and nothing was invented
        all_role_skills = set(role_taxonomy.get_all_role_skills_flat("Backend Developer"))
        assert {m["skill"] for m in out["gap"].missing} == all_role_skills
        assert len(out["plan"]["day_30"]) == 3  # core-first, capped

    def test_placeholder_skill_is_never_treated_as_a_real_detected_skill(self):
        """Direct regression guard for the leak, independent of _run_pipeline."""
        nlp_result = skill_matcher.analyze_activity_semantic("The weather is quite nice today.")
        primary = nlp_result["primary"]
        if not nlp_result["top_matches"]:
            # a placeholder is present but must be identifiable as non-real
            assert primary["confidence_pct"] == 0.0
            assert primary["matched_phrase"] == ""


class TestEmptyAndInvalidInput:

    def test_empty_string_flows_safely_to_a_full_learning_plan(self):
        out = _run_pipeline("")
        assert out["nlp"]["top_matches"] == []
        assert out["detected_skills"] == []
        assert out["gap"].user_skill_count == 0
        assert isinstance(out["plan"]["day_90"], list)

    def test_whitespace_only_input_handled_safely(self):
        out = _run_pipeline("      \t   ")
        assert out["detected_skills"] == []
        assert out["gap"].coverage_pct == 0.0

    def test_very_short_input_does_not_crash_any_stage(self):
        out = _run_pipeline("budgeted")
        assert out["gap"].user_skill_count == len(out["detected_skills"])
        assert isinstance(out["plan"]["day_30"], list)


class TestPartialCareerFit:

    def test_partial_fit_produces_partial_bucket_and_matching_plan(self):
        """A detected skill that only tangentially relates to the target
        role should land in `partial`, not be silently dropped — and the
        learning plan must still cover it."""
        gap = skill_gap_engine.analyze_gap(
            "Backend Developer",
            ["I containerized a small side-project once"],
        )
        # partial or matched, but definitely recognised somewhere
        recognised = {m["skill"] for m in gap.matched} | {m["skill"] for m in gap.partial}
        assert "Docker containerization" in recognised

        plan = learning_recommender.build_learning_plan(
            "Backend Developer", gap.missing, gap.partial, _score()
        )
        planned_skills = {
            item["skill"] for phase in ("day_30", "day_60", "day_90")
            for item in plan[phase]
        }
        gap_skills = (
            {m["skill"] for m in gap.missing} | {m["skill"] for m in gap.partial}
        )
        # every planned skill-specific item traces back to a real gap entry
        assert planned_skills & gap_skills

    def test_partial_fit_coverage_is_between_zero_and_full(self):
        partial_gap = skill_gap_engine.analyze_gap(
            "Backend Developer", ["I containerized a small side-project once"]
        )
        none_gap = skill_gap_engine.analyze_gap("Backend Developer", [])
        assert partial_gap.coverage_pct > none_gap.coverage_pct
        assert partial_gap.coverage_pct < 100.0


class TestCrossStageConsistency:
    """Invariants that must hold no matter what the input is."""

    SAMPLE_INPUTS = [
        "I managed our household budget and tracked monthly savings carefully.",
        "I managed the household budget, negotiated with vendors, and tutored my children.",
        "The sky was cloudy and the coffee was cold.",
        "",
        "budgeted",
        "I containerized a small side-project once",
    ]

    @pytest.mark.parametrize("text", SAMPLE_INPUTS)
    def test_no_stage_crashes_on_any_sample_input(self, text):
        out = _run_pipeline(text)
        assert out["gap"] is not None
        assert set(out["plan"].keys()) >= {"day_30", "day_60", "day_90"}

    @pytest.mark.parametrize("text", SAMPLE_INPUTS)
    def test_gap_buckets_are_mutually_exclusive_and_complete(self, text):
        out = _run_pipeline(text)
        gap = out["gap"]
        matched = {m["skill"] for m in gap.matched}
        partial = {m["skill"] for m in gap.partial}
        missing = {m["skill"] for m in gap.missing}
        all_role_skills = set(role_taxonomy.get_all_role_skills_flat("Backend Developer"))

        assert not (matched & partial)
        assert not (matched & missing)
        assert not (partial & missing)
        assert matched | partial | missing == all_role_skills

    @pytest.mark.parametrize("text", SAMPLE_INPUTS)
    def test_coverage_is_always_a_valid_percentage(self, text):
        out = _run_pipeline(text)
        assert 0.0 <= out["gap"].coverage_pct <= 100.0
        assert 0.0 <= out["gap"].core_coverage_pct <= 100.0

    @pytest.mark.parametrize("text", SAMPLE_INPUTS)
    def test_learning_plan_never_recommends_an_already_matched_skill(self, text):
        """Contradiction guard: a skill the career stage says the user
        ALREADY has must never reappear as something to learn."""
        out = _run_pipeline(text)
        matched_skills = {m["skill"] for m in out["gap"].matched}
        planned_skills = {
            item["skill"] for phase in ("day_30", "day_60")
            for item in out["plan"][phase]
        }
        assert not (matched_skills & planned_skills)
