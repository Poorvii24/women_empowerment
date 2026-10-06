"""
nlp/evaluate.py
=================
Measurable evaluation harness for nlp/skill_matcher.py against a small,
manually labelled dataset (nlp/eval_dataset.json).

This module does NOT modify, wrap, or special-case the matching algorithm —
it only calls the existing public entry point,
`skill_matcher.analyze_activity_semantic()`, exactly the way app.py does,
and scores whatever comes back. The dataset lives in its own JSON file
(nlp/eval_dataset.json) so the labels are visible/auditable independently of
this scoring code, and nothing here hardcodes an expected outcome for any
specific example — all expectations come from that file.

Methodology
-----------
Each example has a set of `expected_skills` (0, 1, or several skill names).
For each example we take the model's `top_matches` list (already ranked by
confidence — see skill_matcher.analyze_activity_semantic) and derive:

  - predicted@1 = the single top-ranked skill (or none, if top_matches is
    empty)
  - predicted@3 = the set of the top 3 ranked skills (or fewer, if the model
    returned fewer than 3)

Multi-label precision / recall / F1 (the metrics requested) are computed
using **micro-averaging over predicted@3 vs. expected_skills**, treating
skill matching as a multi-label set-prediction problem:

    TP = |predicted@3 ∩ expected|
    FP = |predicted@3 \\ expected|      (predicted but not expected)
    FN = |expected \\ predicted@3|      (expected but not predicted)

    precision = TP / (TP + FP)   -- 0 if TP+FP == 0 (nothing was predicted)
    recall    = TP / (TP + FN)   -- 1 if TP+FN == 0 (nothing was expected,
                                     and nothing was predicted, i.e. a
                                     correctly-handled "no relevant skill"
                                     example counts as perfect recall)
    f1        = harmonic mean of the two (0 if precision+recall == 0)

TP/FP/FN are summed across ALL examples first ("micro" averaging) and the
final precision/recall/F1 are computed once from those totals — this is
standard micro-averaging and is more robust than per-example macro-averaging
when some examples have zero expected skills (macro-F1 is undefined for a
0/0 example; micro avoids that entirely by pooling counts globally).

We use predicted@3 (not predicted@1) for precision/recall/F1 because several
dataset examples are genuinely multi-skill — scoring only the single top
prediction against a multi-skill label would structurally cap recall well
below 1.0 even for a perfect matcher. Top-1 and Top-3 ACCURACY (see below)
separately report the single-best-guess behavior, so both views are
available.

Top-1 accuracy: fraction of examples where predicted@1 is IN expected_skills
(for a no-skill example, this counts as correct only if the model produced
no top match at all, i.e. predicted@1 is None).

Top-3 accuracy: fraction of examples where AT LEAST ONE of expected_skills
appears in predicted@3 (for a no-skill example, correct only if
predicted@3 is empty).

Reproducibility: analyze_activity_semantic() is a deterministic function of
its input text and the cached skill embeddings (no randomness, no sampling),
so re-running this module against the same dataset and the same installed
model always produces the same metrics.
"""
import json
import logging
import os

from . import skill_matcher

logger = logging.getLogger("isis.nlp.evaluate")

_THIS_DIR = os.path.dirname(__file__)
DEFAULT_DATASET_PATH = os.path.join(_THIS_DIR, "eval_dataset.json")


def load_dataset(path: str = DEFAULT_DATASET_PATH) -> list[dict]:
    """Loads and returns the list of labelled examples from the dataset file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["examples"]


def _predict(example_text: str, top_n: int = 3) -> dict:
    """
    Runs the existing skill_matcher pipeline, unmodified, on one example.
    Returns {"top1": str|None, "top3": list[str]}.
    """
    result = skill_matcher.analyze_activity_semantic(example_text, top_n=top_n)
    top_matches = result.get("top_matches", [])
    top1 = top_matches[0]["skill"] if top_matches else None
    top3 = [m["skill"] for m in top_matches[:3]]
    return {"top1": top1, "top3": top3}


def evaluate(dataset: list[dict] = None) -> dict:
    """
    Runs the full evaluation and returns a dict with the aggregate metrics
    plus a per-example breakdown (useful for debugging/inspection, not
    required by the headline metrics).
    """
    if dataset is None:
        dataset = load_dataset()

    total_tp = total_fp = total_fn = 0
    top1_correct = 0
    top3_correct = 0
    per_example = []

    for ex in dataset:
        text = ex["text"]
        expected = set(ex.get("expected_skills", []))
        pred = _predict(text)
        predicted_top3 = set(pred["top3"])

        tp = len(predicted_top3 & expected)
        fp = len(predicted_top3 - expected)
        fn = len(expected - predicted_top3)
        total_tp += tp
        total_fp += fp
        total_fn += fn

        # Top-1 accuracy: correct if the single best guess is one of the
        # expected skills, OR (for a no-skill example) if the model made no
        # top guess at all.
        if expected:
            is_top1_correct = pred["top1"] in expected
        else:
            is_top1_correct = pred["top1"] is None
        top1_correct += int(is_top1_correct)

        # Top-3 accuracy: correct if any expected skill appears anywhere in
        # the top 3, OR (for a no-skill example) if the top 3 is empty.
        if expected:
            is_top3_correct = len(predicted_top3 & expected) > 0
        else:
            is_top3_correct = len(predicted_top3) == 0
        top3_correct += int(is_top3_correct)

        per_example.append({
            "id": ex.get("id"),
            "text": text,
            "expected": sorted(expected),
            "predicted_top1": pred["top1"],
            "predicted_top3": pred["top3"],
            "top1_correct": is_top1_correct,
            "top3_correct": is_top3_correct,
        })

    n = len(dataset)
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    top1_accuracy = top1_correct / n if n else 0.0
    top3_accuracy = top3_correct / n if n else 0.0

    return {
        "num_examples": n,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "top1_accuracy": round(top1_accuracy, 4),
        "top3_accuracy": round(top3_accuracy, 4),
        "totals": {"tp": total_tp, "fp": total_fp, "fn": total_fn},
        "per_example": per_example,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = evaluate()
    print(f"Examples evaluated: {results['num_examples']}")
    print(f"Precision:          {results['precision']:.4f}")
    print(f"Recall:             {results['recall']:.4f}")
    print(f"F1-score:           {results['f1']:.4f}")
    print(f"Top-1 accuracy:     {results['top1_accuracy']:.4f}")
    print(f"Top-3 accuracy:     {results['top3_accuracy']:.4f}")
    print()
    print("Per-example breakdown:")
    for ex in results["per_example"]:
        mark1 = "OK" if ex["top1_correct"] else "MISS"
        mark3 = "OK" if ex["top3_correct"] else "MISS"
        print(f"  [{ex['id']:15s}] top1={mark1:4s} top3={mark3:4s}  "
              f"expected={ex['expected']}  predicted_top1={ex['predicted_top1']!r}")


if __name__ == "__main__":
    main()
