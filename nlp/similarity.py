"""
nlp/similarity.py
====================
Pure-numpy similarity and ranking math. No dependency on sentence-transformers
or Flask, which makes this module trivial to unit test in isolation.

Two scores are surfaced for every match, deliberately kept distinct:

    similarity   — the raw cosine similarity (-1.0 to 1.0, in practice usually
                   0.1-0.7 for short, unrelated-domain sentence pairs from
                   general-purpose MiniLM embeddings). This is the literal,
                   unadjusted geometric distance between two embeddings.

    confidence   — a 0-100% RELATIVE match score, computed via softmax over
                   the similarity scores of all candidate skills for this one
                   query. This is a "match confidence" / "match score" in the
                   colloquial sense — how much better this skill looks than
                   the alternatives for THIS query — not a calibrated
                   statistical probability. It has not been validated against
                   real-world accuracy (e.g. "70% confidence" does not mean
                   "correct 70% of the time"), and it is directly comparable
                   only *within* one query's own candidate set, not across
                   different queries or different numbers of skills. Treat it
                   as a ranking/triage signal, not a probability estimate.

Showing both numbers is intentional: it keeps the system honest (the raw
number is never hidden) while still giving a more interpretable headline
percentage for the UI.
"""
import numpy as np


def cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between a single query vector and every row
    of `matrix`.

    Assumes both `query_vec` and the rows of `matrix` are already L2-normalized
    (embedding_engine.encode() guarantees this) — in that case cosine
    similarity is just the dot product, which is what this function computes.
    If vectors are NOT pre-normalized, this function normalizes them itself
    so it is still correct (just slightly slower) when used standalone
    (e.g. directly in tests with hand-built vectors).

    Returns a 1D array of similarities, one per row in `matrix`.
    """
    if matrix.shape[0] == 0:
        return np.zeros((0,), dtype="float32")

    q_norm = np.linalg.norm(query_vec)
    if q_norm > 0:
        query_vec = query_vec / q_norm

    row_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    row_norms[row_norms == 0] = 1.0  # avoid division by zero for any all-zero row
    normalized_matrix = matrix / row_norms

    return normalized_matrix @ query_vec


def softmax_confidence(scores: np.ndarray, temperature: float = 0.1) -> np.ndarray:
    """
    Convert raw similarity scores into a 0-1 RELATIVE match-score
    distribution via softmax, so the scores sum to 1 across all candidates.
    This is a ranking/triage signal ("how much better does this candidate
    look than the others right now"), not a calibrated statistical
    probability — see the module docstring above for why that distinction
    matters and shouldn't be blurred in any UI-facing wording.

    `temperature` controls how "sharp" the distribution is:
      - Lower temperature -> the top score dominates more (more decisive).
      - Higher temperature -> scores are closer to uniform (less decisive).
    0.1 was chosen empirically for MiniLM cosine similarities in the
    ~0.1-0.6 range typical of short activity sentences vs. skill
    descriptions — it's small enough that a clearly-better match (e.g.
    0.55 vs 0.30) produces a confidently high confidence (>80%), while two
    near-tied matches (e.g. 0.40 vs 0.38) stay close together rather than
    one swamping the other.

    Numerically stable: subtracts the max score before exponentiating.
    """
    if scores.shape[0] == 0:
        return np.zeros((0,), dtype="float32")

    scaled = scores / max(temperature, 1e-8)
    shifted = scaled - np.max(scaled)
    exp_scores = np.exp(shifted)
    return exp_scores / np.sum(exp_scores)


def top_n_matches(scores: np.ndarray, n: int = 3) -> list[int]:
    """
    Return the indices of the top-`n` highest scores, sorted descending.
    If there are fewer than `n` candidates, returns all of them.
    """
    if scores.shape[0] == 0:
        return []
    n = min(n, scores.shape[0])
    # argpartition for O(k) selection, then sort just the top-k for the final order
    top_idx = np.argpartition(scores, -n)[-n:]
    return list(top_idx[np.argsort(scores[top_idx])[::-1]])
