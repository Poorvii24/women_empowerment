"""
services/skill_gap_engine.py
==============================
Compares a user's demonstrated skills (from activity history + resume)
against a target role's required skills using semantic embeddings.

Why embeddings instead of string matching:
  "managed household budget" should match "Financial Management" — but
  a simple string comparison gives 0. Cosine similarity over MiniLM
  embeddings gives ~0.62, which correctly identifies the match.

The engine returns three buckets:
  matched     — skills you demonstrably have (similarity >= threshold)
  partial     — skills you're partway toward (similarity in lower band)
  missing     — skills with no meaningful overlap with your history

Plus a coverage_pct (0–100) which feeds the Career Readiness Score.
"""
import logging
from dataclasses import dataclass

import numpy as np

from nlp import embedding_engine
from services.role_taxonomy import get_all_role_skills_flat, get_role_skills

logger = logging.getLogger("isis.services.skill_gap_engine")

# Cosine similarity thresholds (using normalized dot product, so range is 0–1)
MATCH_THRESHOLD = 0.42      # above this → "you have this skill"
PARTIAL_THRESHOLD = 0.28    # above this (but below MATCH) → "partial overlap"


@dataclass
class SkillGapResult:
    role: str
    matched: list[dict]      # [{"skill": str, "similarity": float, "matched_by": str}]
    partial: list[dict]      # same shape, lower similarity
    missing: list[dict]      # [{"skill": str, "tier": "core"|"supporting"}]
    coverage_pct: float      # 0–100, weighted: core skills count double
    core_coverage_pct: float # 0–100, just core skills
    user_skill_count: int    # how many user skills were provided


def _all_missing_result(role_name: str, user_skill_count: int) -> SkillGapResult:
    """
    Shared by both 'nothing to compare' cases in analyze_gap(): an empty
    user_skills list, and a non-empty list that contains no usable (non-blank)
    skill text. Still calls get_role_skills() so an unknown role_name raises
    the same clear KeyError it would in the normal path, rather than silently
    returning an empty-but-plausible-looking result for a typo'd role name.
    """
    role_data = get_role_skills(role_name)
    all_skills = get_all_role_skills_flat(role_name)
    missing = [
        {"skill": s, "tier": "core" if s in role_data["core"] else "supporting"}
        for s in all_skills
    ]
    return SkillGapResult(
        role=role_name,
        matched=[],
        partial=[],
        missing=missing,
        coverage_pct=0.0,
        core_coverage_pct=0.0,
        user_skill_count=user_skill_count,
    )


def analyze_gap(
    role_name: str,
    user_skills: list[str],
    top_n_user: int = 25,
) -> SkillGapResult:
    """
    Main entry point.

    user_skills: flat list of skill phrases from the user's activity history
                 AND/OR resume skills section — the caller merges both sources.
    role_name:   one of the keys in role_taxonomy.TARGET_ROLES
    """
    if not user_skills:
        # Nothing to compare — return everything as missing
        return _all_missing_result(role_name, user_skill_count=0)

    # Limit user skill list to avoid sending enormous prompts if user has
    # hundreds of activity phrases (realistically capped by DB limit=50)
    user_skills_clean = [s.strip() for s in user_skills if s.strip()][:top_n_user]

    if not user_skills_clean:
        # user_skills was non-empty but every entry was blank/whitespace
        # (e.g. stray empty strings surviving upstream dedup) — same
        # "nothing to compare" outcome as the empty-list case above, not a
        # crash. Previously this fell through to np.argmax() on an empty
        # array and raised ValueError.
        return _all_missing_result(role_name, user_skill_count=0)

    role_data = get_role_skills(role_name)
    role_skills_flat = get_all_role_skills_flat(role_name)

    # Encode both sides
    all_texts = user_skills_clean + role_skills_flat
    all_vecs = embedding_engine.encode(all_texts)

    user_vecs = all_vecs[: len(user_skills_clean)]
    role_vecs = all_vecs[len(user_skills_clean):]

    # For each required skill, find the best-matching user skill
    matched, partial, missing = [], [], []

    for i, role_skill in enumerate(role_skills_flat):
        tier = "core" if role_skill in role_data["core"] else "supporting"

        # Cosine similarity of this role skill against every user skill
        sims = role_vecs[i] @ user_vecs.T      # dot product = cosine (both L2-normalized)
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        best_user_skill = user_skills_clean[best_idx]

        if best_sim >= MATCH_THRESHOLD:
            matched.append({
                "skill": role_skill,
                "tier": tier,
                "similarity": round(best_sim, 3),
                "matched_by": best_user_skill,
            })
        elif best_sim >= PARTIAL_THRESHOLD:
            partial.append({
                "skill": role_skill,
                "tier": tier,
                "similarity": round(best_sim, 3),
                "matched_by": best_user_skill,
            })
        else:
            missing.append({"skill": role_skill, "tier": tier})

    # Weighted coverage: core skills count 2x, supporting 1x
    n_core = len(role_data["core"])
    n_supp = len(role_data["supporting"])
    total_weight = n_core * 2 + n_supp

    matched_core_weight = sum(2 if m["tier"] == "core" else 1 for m in matched)
    partial_core_weight = sum((1 if m["tier"] == "core" else 0.5) for m in partial)

    coverage_pct = min(100.0, round(
        (matched_core_weight + partial_core_weight) / max(total_weight, 1) * 100, 1
    ))

    core_matched = sum(1 for m in matched if m["tier"] == "core")
    core_partial = sum(1 for m in partial if m["tier"] == "core")
    core_coverage_pct = min(100.0, round(
        (core_matched * 2 + core_partial) / max(n_core * 2, 1) * 100, 1
    ))

    # Sort results: matched by similarity desc, missing core-first
    matched.sort(key=lambda x: x["similarity"], reverse=True)
    partial.sort(key=lambda x: x["similarity"], reverse=True)
    missing.sort(key=lambda x: (0 if x["tier"] == "core" else 1))

    return SkillGapResult(
        role=role_name,
        matched=matched,
        partial=partial,
        missing=missing,
        coverage_pct=coverage_pct,
        core_coverage_pct=core_coverage_pct,
        user_skill_count=len(user_skills_clean),
    )
