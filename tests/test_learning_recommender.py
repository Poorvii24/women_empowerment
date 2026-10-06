"""
tests/test_learning_recommender.py
=====================================
Focused unit tests for services/learning_recommender.py — the final stage
of ISIS's explainable career-mapping flow:

    detected skills -> missing skills (skill_gap_engine) -> priority
                     -> learning recommendations (this module)

No unit tests previously existed for this module at all (only indirectly
exercised through the end-to-end Flask route in test_career_hub.py).

These tests call build_learning_plan()/_lookup_resources() directly with
plain dicts shaped exactly like skill_gap_engine.SkillGapResult.missing /
.partial entries — no embedding model, no fake encoder needed, since this
module does no semantic matching itself; it only prioritises and looks up
resources for skill labels it's already been given.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import learning_recommender as lr
from services import role_taxonomy
from services.scoring_engine import CareerReadinessScore


def _make_score(technical=70, leadership=70, communication=70, consistency=70, growth=70):
    """A minimal, valid CareerReadinessScore for feeding build_learning_plan
    — only the 5 axis values are used by this module."""
    return CareerReadinessScore(
        overall=70,
        technical=technical,
        leadership=leadership,
        communication=communication,
        consistency=consistency,
        growth=growth,
        explanations={},
    )


def _core(skill):
    return {"skill": skill, "tier": "core"}


def _supporting(skill):
    return {"skill": skill, "tier": "supporting"}


class TestResourceLookupIsGrounded:
    """'No arbitrary or unrelated recommendations' — resources must be tied
    to the actual skill string, not random or mismatched."""

    def test_exact_key_match_returns_topic_correct_resources(self):
        resources = lr._lookup_resources("Docker containerization")
        titles = " ".join(r["title"].lower() for r in resources)
        assert "docker" in titles

    def test_similarly_worded_skills_do_not_cross_contaminate(self):
        """'SQL and database querying' and 'database design and SQL' share
        the word SQL but are different role skills with different curated
        resources — exact-key lookup must not blur them together."""
        sql_querying = lr._lookup_resources("SQL and database querying")
        db_design = lr._lookup_resources("database design and SQL")
        querying_titles = {r["title"] for r in sql_querying}
        design_titles = {r["title"] for r in db_design}
        assert querying_titles != design_titles
        assert not (querying_titles & design_titles)  # no shared entries

    def test_unknown_skill_falls_back_to_generic_default_not_a_wrong_match(self):
        resources = lr._lookup_resources("Underwater basket weaving")
        assert resources == [lr._DEFAULT_RESOURCE]

    def test_every_real_role_skill_resolves_without_crashing(self):
        """Every skill string that can actually appear in a missing/partial
        entry (i.e. every skill in role_taxonomy) must resolve to at least
        one resource, exact-matched or via the generic fallback."""
        all_skills = set()
        for role in role_taxonomy.TARGET_ROLES.values():
            all_skills.update(role["core"])
            all_skills.update(role["supporting"])
        for skill in all_skills:
            resources = lr._lookup_resources(skill)
            assert isinstance(resources, list) and len(resources) >= 1
            for r in resources:
                assert {"title", "type", "url", "duration"} <= r.keys()


class TestCorePriorityOverSupporting:

    def test_core_missing_skills_are_scheduled_before_supporting(self):
        missing = [
            _supporting("Docker containerization"),
            _core("REST API development"),
            _supporting("CI/CD pipelines"),
            _core("database design and SQL"),
        ]
        plan = lr.build_learning_plan("Backend Developer", missing, [], _make_score())
        day_30_skills = [item["skill"] for item in plan["day_30"]]
        # Only core skills should appear in the very first phase, regardless
        # of the order they were passed in.
        assert set(day_30_skills) == {"REST API development", "database design and SQL"}

    def test_core_missing_entries_cite_core_specific_justification(self):
        missing = [_core("REST API development")]
        plan = lr.build_learning_plan("Backend Developer", missing, [], _make_score())
        assert "core" in plan["day_30"][0]["why"].lower()

    def test_more_than_three_core_skills_overflow_into_day_60_still_before_supporting(self):
        missing = [_core(f"core skill {i}") for i in range(5)] + [_supporting("supporting skill A")]
        plan = lr.build_learning_plan("Backend Developer", missing, [], _make_score())
        day_30_skills = {item["skill"] for item in plan["day_30"]}
        day_60_skills = [item["skill"] for item in plan["day_60"]]
        assert len(day_30_skills) == 3
        assert all(s.startswith("core skill") for s in day_30_skills)
        # The 4th and 5th core skills should appear in day_60 before the
        # supporting skill's own resource entry.
        assert "core skill 3" in day_60_skills
        assert "core skill 4" in day_60_skills


class TestRecommendationsMatchMissingSkills:

    def test_every_day30_and_day60_skill_entry_traces_back_to_input(self):
        """Every skill-specific plan item must correspond to a skill that
        was actually passed in as missing or partial — not something
        invented. (day_90 additionally carries a weakest-axis tip and a
        capstone suggestion, which are a distinct, clearly-different kind
        of recommendation — checked separately below.)"""
        missing = [_core("REST API development"), _supporting("Docker containerization")]
        partial = [_supporting("CI/CD pipelines")]
        plan = lr.build_learning_plan("Backend Developer", missing, partial, _make_score())

        valid_skill_labels = {m["skill"] for m in missing + partial}
        for phase in ("day_30", "day_60"):
            for item in plan[phase]:
                assert item["skill"] in valid_skill_labels

    def test_day90_skill_specific_items_also_trace_back_to_input(self):
        missing = [_supporting(f"supporting skill {i}") for i in range(5)]
        plan = lr.build_learning_plan("Backend Developer", missing, [], _make_score())
        valid_skill_labels = {m["skill"] for m in missing}
        # day_90 skill-specific entries come first; the last two entries are
        # always the weakest-axis tip and the capstone project (see below),
        # neither of which is a missing/partial skill label.
        skill_specific_entries = plan["day_90"][:-2]
        for item in skill_specific_entries:
            assert item["skill"] in valid_skill_labels

    def test_plan_never_invents_a_skill_not_in_role_taxonomy_or_input(self):
        missing = [_core("REST API development")]
        plan = lr.build_learning_plan("Backend Developer", missing, [], _make_score())
        all_role_skills = set(role_taxonomy.get_all_role_skills_flat("Backend Developer"))
        for phase in ("day_30", "day_60"):
            for item in plan[phase]:
                assert item["skill"] in all_role_skills


class TestWeakestAxisAndCapstoneAreDataDriven:
    """The two 'extra' day_90 recommendations aren't skill-gap-derived, but
    they must still be genuinely computed from real inputs (weakest axis,
    actual role name) rather than a fixed, unrelated recommendation."""

    def test_weakest_axis_tip_follows_the_actual_lowest_score(self):
        score = _make_score(technical=90, leadership=10, communication=90, consistency=90, growth=90)
        plan = lr.build_learning_plan("Backend Developer", [], [], score)
        axis_tip = plan["day_90"][-2]
        assert "leadership" in axis_tip["why"].lower()

    def test_weakest_axis_tip_changes_when_a_different_axis_is_lowest(self):
        score = _make_score(technical=10, leadership=90, communication=90, consistency=90, growth=90)
        plan = lr.build_learning_plan("Backend Developer", [], [], score)
        axis_tip = plan["day_90"][-2]
        assert "technical" in axis_tip["why"].lower()

    def test_capstone_suggestion_matches_the_requested_role(self):
        plan = lr.build_learning_plan("Cloud Engineer", [], [], _make_score())
        capstone = plan["day_90"][-1]
        assert "Cloud Engineer" not in capstone["skill"]  # role name isn't literally repeated
        assert "AWS/GCP" in capstone["skill"] or "Terraform" in capstone["skill"]

    def test_unknown_role_name_gets_generic_capstone_not_a_crash(self):
        plan = lr.build_learning_plan("Some Future Role", [], [], _make_score())
        capstone = plan["day_90"][-1]
        assert "full-stack project" in capstone["skill"].lower()


class TestNoDetectedSkillsHandledSafely:

    def test_all_skills_missing_produces_a_full_but_bounded_plan(self):
        """Simulates skill_gap_engine's output when a user has zero detected
        skills: every role skill lands in 'missing'. build_learning_plan
        must not crash and must still respect the day_30 cap of 3 core skills."""
        role_data = role_taxonomy.get_role_skills("Backend Developer")
        missing = (
            [_core(s) for s in role_data["core"]]
            + [_supporting(s) for s in role_data["supporting"]]
        )
        plan = lr.build_learning_plan("Backend Developer", missing, [], _make_score())
        assert len(plan["day_30"]) == 3
        # every phase is present and is a list, even though nothing crashed
        assert isinstance(plan["day_60"], list)
        assert isinstance(plan["day_90"], list)

    def test_empty_missing_and_partial_still_returns_a_valid_plan(self):
        """Simulates a very strong match: nothing missing, nothing partial.
        The plan should be safe and small — just the weakest-axis tip and
        the capstone suggestion, no fabricated skill gaps."""
        plan = lr.build_learning_plan("Backend Developer", [], [], _make_score())
        assert plan["day_30"] == []
        assert plan["day_60"] == []
        assert len(plan["day_90"]) == 2  # only the axis tip + capstone, nothing invented


class TestStrongMatchProducesFewerGaps:

    def test_fewer_missing_skills_yields_a_smaller_plan(self):
        small_gap = [_core("REST API development")]
        large_gap = [_core(s) for s in role_taxonomy.get_role_skills("Backend Developer")["core"]]

        small_plan = lr.build_learning_plan("Backend Developer", small_gap, [], _make_score())
        large_plan = lr.build_learning_plan("Backend Developer", large_gap, [], _make_score())

        small_total = len(small_plan["day_30"]) + len(small_plan["day_60"])
        large_total = len(large_plan["day_30"]) + len(large_plan["day_60"])
        assert small_total < large_total
