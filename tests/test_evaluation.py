"""
tests/test_evaluation.py
===========================
Tests for the evaluation dataset (nlp/eval_dataset.json) and evaluation
harness (nlp/evaluate.py). These do NOT test skill_matcher's matching
quality itself (that's covered by tests/test_nlp_pipeline.py) — they verify
that the dataset is well-formed, every label is real, and the evaluation
math is correct and safe on edge cases (empty predictions, no-skill
examples, out-of-range metrics).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import numpy as np
import pytest

from nlp import embedding_engine, evaluate, skill_matcher

_VOCAB = [
    "budget", "finance", "money", "savings",
    "teach", "tutor", "mentor", "educat",
    "lead", "supervis", "team", "motivat",
    "cook", "meal", "nutrition", "food",
    "care", "health", "patient", "elder",
    "negoti", "vendor", "celebrat",
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
def _use_fake_encoder():
    """Same deterministic-encoder pattern as test_nlp_pipeline.py, isolated
    to its own cache file so it never collides with other test modules."""
    embedding_engine.set_encoder_override(_fake_encoder)
    skill_matcher._skill_profiles = None
    skill_matcher._skill_embeddings = None
    skill_matcher._skills_json_hash = None
    original_cache_path = skill_matcher.CACHE_PATH
    skill_matcher.CACHE_PATH = original_cache_path + ".test_evaluation.npz"
    yield
    embedding_engine.set_encoder_override(None)
    if os.path.exists(skill_matcher.CACHE_PATH):
        os.remove(skill_matcher.CACHE_PATH)
    skill_matcher.CACHE_PATH = original_cache_path
    skill_matcher._skill_profiles = None
    skill_matcher._skill_embeddings = None
    skill_matcher._skills_json_hash = None


class TestDatasetFormat:

    def test_dataset_loads_and_is_nonempty(self):
        dataset = evaluate.load_dataset()
        assert isinstance(dataset, list)
        assert len(dataset) >= 10  # a "small" dataset, but a real one

    def test_every_example_has_required_fields(self):
        dataset = evaluate.load_dataset()
        for ex in dataset:
            assert "id" in ex and isinstance(ex["id"], str) and ex["id"]
            assert "text" in ex and isinstance(ex["text"], str)
            assert "expected_skills" in ex and isinstance(ex["expected_skills"], list)

    def test_example_ids_are_unique(self):
        dataset = evaluate.load_dataset()
        ids = [ex["id"] for ex in dataset]
        assert len(ids) == len(set(ids))

    def test_dataset_includes_required_category_coverage(self):
        """Sanity check that the dataset actually covers the categories the
        task asked for, by id-prefix convention (single_/multi_/paraphrase_/
        no_skill_/short_/household_)."""
        dataset = evaluate.load_dataset()
        prefixes = {ex["id"].split("_")[0] for ex in dataset}
        for required in ("single", "multi", "paraphrase", "no", "short", "household"):
            assert any(p.startswith(required) for p in prefixes), f"missing '{required}' examples"

    def test_multi_skill_examples_have_more_than_one_expected_skill(self):
        dataset = evaluate.load_dataset()
        multi_examples = [ex for ex in dataset if ex["id"].startswith("multi_")]
        assert len(multi_examples) >= 2
        for ex in multi_examples:
            assert len(ex["expected_skills"]) >= 2

    def test_no_skill_examples_have_empty_expected_skills(self):
        dataset = evaluate.load_dataset()
        no_skill_examples = [ex for ex in dataset if ex["id"].startswith("no_skill_")]
        assert len(no_skill_examples) >= 2
        for ex in no_skill_examples:
            assert ex["expected_skills"] == []


class TestExpectedSkillsExistInSkillsJson:

    def test_every_expected_skill_is_a_real_skill(self):
        dataset = evaluate.load_dataset()
        skills_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills.json"
        )
        with open(skills_path, encoding="utf-8") as f:
            skills_data = json.load(f)
        valid_skills = {s["professional_skill"] for s in skills_data["skill_mappings"]}

        for ex in dataset:
            for skill in ex["expected_skills"]:
                assert skill in valid_skills, (
                    f"example '{ex['id']}' references unknown skill {skill!r} — "
                    "dataset labels must use existing skills.json names only"
                )


class TestEvaluationRuns:

    def test_evaluate_runs_successfully_on_full_dataset(self):
        results = evaluate.evaluate()
        assert results["num_examples"] == len(evaluate.load_dataset())
        assert "per_example" in results
        assert len(results["per_example"]) == results["num_examples"]

    def test_metrics_are_within_valid_range(self):
        results = evaluate.evaluate()
        for key in ("precision", "recall", "f1", "top1_accuracy", "top3_accuracy"):
            value = results[key]
            assert 0.0 <= value <= 1.0, f"{key} out of [0,1] range: {value}"

    def test_evaluation_is_reproducible(self):
        """Same dataset + same (deterministic) encoder must give identical
        metrics on repeated runs — no randomness anywhere in the pipeline."""
        first = evaluate.evaluate()
        second = evaluate.evaluate()
        assert first["precision"] == second["precision"]
        assert first["recall"] == second["recall"]
        assert first["f1"] == second["f1"]
        assert first["top1_accuracy"] == second["top1_accuracy"]
        assert first["top3_accuracy"] == second["top3_accuracy"]


class TestEvaluationEdgeCasesAndMath:

    def test_empty_dataset_does_not_crash(self):
        results = evaluate.evaluate(dataset=[])
        assert results["num_examples"] == 0
        assert results["top1_accuracy"] == 0.0
        assert results["top3_accuracy"] == 0.0
        # precision/recall on zero examples: no TP/FP/FN at all — recall
        # defaults to 1.0 (vacuously "nothing missed") and precision to 0.0
        # (nothing predicted), matching the documented per-example rule.
        assert 0.0 <= results["precision"] <= 1.0
        assert 0.0 <= results["recall"] <= 1.0

    def test_no_skill_example_with_no_prediction_counts_as_fully_correct(self):
        """A no-skill example where the model correctly predicts nothing
        should contribute 0 FP/FN and count as correct for both accuracies."""
        dataset = [{"id": "synthetic_no_skill", "text": "", "expected_skills": []}]
        results = evaluate.evaluate(dataset=dataset)
        assert results["top1_accuracy"] == 1.0
        assert results["top3_accuracy"] == 1.0
        assert results["totals"] == {"tp": 0, "fp": 0, "fn": 0}

    def test_precision_recall_f1_hand_computed_on_synthetic_dataset(self):
        """Use a tiny synthetic dataset with a known correct fake-encoder
        outcome to verify the precision/recall/F1 arithmetic itself,
        independent of how well the real dataset happens to score.

        NOTE ON EXPECTED NUMBERS: skill_matcher.analyze_activity_semantic()
        now only returns matches that clear a "better than chance" match
        confidence floor (see confidence_floor_pct in nlp/skill_matcher.py),
        rather than always padding to top_n regardless of evidence. For a
        clean single-skill example like these two, that means exactly ONE
        genuinely supported match each, with no filler false positives.
        So for 2 clean single-skill examples: TP=2 (one correct match
        each), FP=0 (no filler), FN=0 (nothing expected was missed).
        precision = 2/2 = 1.0, recall = 2/2 = 1.0, f1 = 1.0.
        """
        dataset = [
            {
                "id": "syn_1",
                "text": "I managed our household budget and tracked monthly savings carefully.",
                "expected_skills": ["Financial Management & Budget Allocation"],
            },
            {
                "id": "syn_2",
                "text": "I tutor and mentor neighborhood kids in maths after school every day.",
                "expected_skills": ["Training, Mentoring & Instruction"],
            },
        ]
        results = evaluate.evaluate(dataset=dataset)
        assert results["totals"] == {"tp": 2, "fp": 0, "fn": 0}
        assert results["precision"] == 1.0
        assert results["recall"] == 1.0
        assert results["f1"] == 1.0
        assert results["top1_accuracy"] == 1.0
        assert results["top3_accuracy"] == 1.0

    def test_metrics_do_not_hardcode_dataset_outcome(self):
        """The evaluation logic must derive its verdict from whatever
        skill_matcher actually returns, not from a hardcoded expectation —
        verified by feeding a deliberately wrong label and confirming the
        harness correctly reports a top-1 MISS rather than silently passing.
        (Top-1 is checked here — always exactly the single best-scoring
        skill — for a simple, unambiguous signal of a genuine miss.)
        """
        dataset = [
            {
                "id": "syn_wrong_label",
                "text": "I managed our household budget and tracked monthly savings carefully.",
                "expected_skills": ["Nutritional Planning & Catering Operations"],  # deliberately wrong
            }
        ]
        results = evaluate.evaluate(dataset=dataset)
        assert results["top1_accuracy"] == 0.0
        assert results["per_example"][0]["predicted_top1"] == "Financial Management & Budget Allocation"
