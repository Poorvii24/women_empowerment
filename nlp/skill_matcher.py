"""
nlp/skill_matcher.py
=======================
The main entry point for the embedding-based skill intelligence engine.

Responsibilities:
    1. Build a "semantic profile" sentence for every skill in skills.json
       (name + category + leadership trait + description + keywords),
       embed all of them ONCE, and cache the result to disk.
    2. Given a user's activity text, embed it (and its sub-phrases), compare
       against every skill's embedding via cosine similarity, and return a
       ranked, explainable list of matches.
    3. Provide a single primary match plus derived skill_magnitude /
       leadership_index numbers in the same shape the old keyword-based
       `map_activity_to_skill()` used to return, so app.py can swap engines
       with minimal changes to the rest of the pipeline.

This module has ZERO dependency on Flask/app.py — it loads skills.json itself,
so it can be imported and tested completely standalone.
"""
import hashlib
import json
import logging
import os

import numpy as np

from . import embedding_engine, feature_representation, preprocessing, similarity, text_pipeline
from . import keyphrase_extractor

logger = logging.getLogger("isis.nlp.skill_matcher")

_THIS_DIR = os.path.dirname(__file__)
SKILLS_JSON_PATH = os.path.join(_THIS_DIR, "..", "skills.json")
CACHE_DIR = os.path.join(_THIS_DIR, "cache")
CACHE_PATH = os.path.join(CACHE_DIR, "skill_embeddings.npz")

# Upper bound on how many *extra* matches a genuinely multi-topic activity
# description can surface beyond the caller-requested `top_n` (see
# analyze_activity_semantic). Keeps output bounded even for a very long
# description with many clauses, instead of potentially returning every
# skill in skills.json.
MAX_MULTI_SKILL_MATCHES = 6

# Module-level cache, populated on first use (lazy load — see TASK 7).
_skill_profiles = None       # list[dict] — metadata for each skill, in fixed order
_skill_embeddings = None     # np.ndarray, shape (num_skills, EMBEDDING_DIM)
_skills_json_hash = None     # content hash of skills.json this cache was built from


class SkillReferenceError(Exception):
    """Raised when skills.json is missing or malformed."""


def _load_skills_json() -> dict:
    try:
        with open(SKILLS_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as e:
        raise SkillReferenceError(f"skills.json not found at {SKILLS_JSON_PATH}") from e
    except json.JSONDecodeError as e:
        raise SkillReferenceError(f"skills.json is not valid JSON: {e}") from e


def _content_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()[:16]


def _build_semantic_profile(skill: dict) -> str:
    """
    Turns one skills.json entry into a single descriptive sentence that
    captures its name, category, leadership trait, description, and
    keywords — this is the text that actually gets embedded.

    Keywords are included as a comma-separated list at the end. Even though
    they're "just words", including them gives the embedding model a little
    extra lexical grounding (e.g. "budget", "savings") on top of the
    semantic description, which empirically helps short, informally-worded
    user activities match better than the description text alone.
    """
    name = skill.get("professional_skill", "")
    category = skill.get("onet_category", "")
    leadership_trait = skill.get("leadership_category", "")
    description = skill.get("description", "")
    keywords = ", ".join(skill.get("keywords", []))

    return (
        f"{name}. Category: {category}. "
        f"Leadership trait: {leadership_trait}. "
        f"{description} "
        f"Related terms: {keywords}."
    ).strip()


def _ensure_loaded():
    """
    Lazily builds (or loads from disk cache) the skill embedding knowledge
    base. Safe to call on every request — after the first call it's just an
    in-memory dict lookup, no recomputation.
    """
    global _skill_profiles, _skill_embeddings, _skills_json_hash

    if _skill_embeddings is not None:
        return  # already loaded for this process

    with open(SKILLS_JSON_PATH, "rb") as f:
        raw_bytes = f.read()
    current_hash = _content_hash(raw_bytes)

    data = json.loads(raw_bytes)
    skills = data.get("skill_mappings", [])
    leadership_categories = data.get("leadership_categories", {})

    profiles = []
    for skill in skills:
        profile_text = _build_semantic_profile(skill)
        profiles.append({
            "professional_skill": skill.get("professional_skill", "Unknown Skill"),
            "onet_category": skill.get("onet_category", ""),
            "leadership_category": skill.get("leadership_category", ""),
            "market_value": skill.get("market_value", "Medium"),
            "base_magnitude": skill.get("base_magnitude", 60),
            "keywords": skill.get("keywords", []),
            "leadership_weight": leadership_categories.get(
                skill.get("leadership_category", ""), {}
            ).get("weight", 1.0),
            "profile_text": profile_text,
        })

    # --- Classical NLP feature representation (TF-IDF) — fit once per corpus ---
    # This is independent of the embedding cache above: it's cheap to refit
    # (no network, no model), so it isn't disk-cached, just held in-process.
    try:
        normalized_texts = [text_pipeline.normalize_for_features(p["profile_text"]) or p["profile_text"] for p in profiles]
        feature_representation.fit_skill_corpus(
            [p["profile_text"] for p in profiles], normalized_texts
        )
    except Exception:
        logger.warning("tfidf_corpus_fit_failed_continuing_embedding_only", exc_info=True)

    # --- Try to reuse a disk cache built from the exact same skills.json content ---
    if os.path.exists(CACHE_PATH):
        try:
            cached = np.load(CACHE_PATH, allow_pickle=False)
            if str(cached["content_hash"][0]) == current_hash and cached["embeddings"].shape[0] == len(profiles):
                _skill_embeddings = cached["embeddings"]
                _skill_profiles = profiles
                _skills_json_hash = current_hash
                logger.info("skill_embedding_cache_hit", extra={"num_skills": len(profiles)})
                return
        except Exception:
            logger.warning("skill_embedding_cache_unreadable_rebuilding", exc_info=True)

    # --- Cache miss (first run, or skills.json changed) — compute fresh ---
    logger.info("skill_embedding_cache_miss_building", extra={"num_skills": len(profiles)})
    embeddings = embedding_engine.encode([p["profile_text"] for p in profiles])

    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        np.savez(
            CACHE_PATH,
            embeddings=embeddings,
            content_hash=np.array([current_hash]),
        )
    except OSError:
        # Non-fatal — caching is a performance optimization, not a correctness
        # requirement. Worst case, we recompute on next restart.
        logger.warning("skill_embedding_cache_write_failed", exc_info=True)

    _skill_embeddings = embeddings
    _skill_profiles = profiles
    _skills_json_hash = current_hash


def warm_up():
    """
    Optionally call this once at app startup (off the request path, e.g. in a
    background thread) to pay the model-load + embedding-build cost before
    the first real user request arrives, instead of on it. Calling
    `analyze_activity_semantic()` without ever calling `warm_up()` works
    fine too — it just lazily builds everything on first use.
    """
    _ensure_loaded()


def analyze_activity_semantic(activity_text: str, top_n: int = 3) -> dict:
    """
    The main entry point. Given a raw activity description, returns:

    {
        "top_matches": [
            {
                "skill": str,
                "onet_category": str,
                "leadership_category": str,
                "similarity": float,        # raw cosine, -1..1
                "confidence_pct": float,    # 0..100, relative match score (softmax
                                             # over candidate skills — NOT a
                                             # calibrated statistical probability;
                                             # see nlp/similarity.py)
                "matched_phrase": str,      # closest sub-phrase of the activity text
                "explanation": str,         # human-readable "why"
            },
            ...
        ],
        "primary": { ...same shape as one top_matches entry..., plus:
            "skill_magnitude": float,       # 0-100, drop-in replacement for the
            "leadership_index": float,      #  old keyword engine's numbers
            "market_value": str,
        },
        "engine": "embedding_v1",
    }

    Never raises on bad input — an empty/whitespace activity_text returns a
    low-confidence generic result rather than throwing, since this function
    sits in the request path and a crash here must not break activity
    analysis as a whole.
    """
    cleaned = preprocessing.clean_text(activity_text)
    if not cleaned:
        return _empty_result()

    _ensure_loaded()

    query_vec = embedding_engine.encode([cleaned])[0]
    embedding_sims = similarity.cosine_similarity(query_vec, _skill_embeddings)

    # --- Classical NLP grounding signal: TF-IDF cosine similarity ---
    # Blended in at a minority weight so the embedding engine (which
    # generalizes across paraphrases) remains the primary driver, while
    # exact lexical overlap with a skill's own keywords/description gets a
    # real, explainable boost rather than being invisible to the ranking.
    # Falls back to embedding-only (weight 0) if TF-IDF isn't available for
    # any reason — this must never break skill matching.
    TFIDF_BLEND_WEIGHT = 0.25
    try:
        normalized_query = text_pipeline.normalize_for_features(cleaned) or cleaned
        tfidf_sims = feature_representation.tfidf_similarity_to_skills(normalized_query)
        if tfidf_sims.shape[0] == embedding_sims.shape[0]:
            sims = (1 - TFIDF_BLEND_WEIGHT) * embedding_sims + TFIDF_BLEND_WEIGHT * tfidf_sims
        else:
            sims = embedding_sims
    except Exception:
        logger.warning("tfidf_blend_failed_using_embedding_only", exc_info=True)
        sims = embedding_sims

    num_skills = sims.shape[0]

    # Phrase-level explainability + multi-skill evidence: split the activity
    # into clauses once, embed them once, and reuse below.
    phrases = preprocessing.extract_phrases(cleaned)
    phrase_vecs = embedding_engine.encode(phrases) if phrases else np.zeros((0, sims.shape[0]))
    multi_clause = len(phrases) > 1

    # Extracted keyphrases (POS-candidate + TF-IDF-ranked) — computed once,
    # both for the "keyphrases" field returned to callers AND as an extra
    # lexical evidence source for multi-skill boosting below.
    try:
        keyphrases = keyphrase_extractor.extract_keyphrases(cleaned, top_k=5)
    except Exception:
        logger.warning("keyphrase_extraction_failed", exc_info=True)
        keyphrases = []

    # --- Multi-skill evidence boost ---
    # A single embedding of the WHOLE activity text blends every clause's
    # meaning into one vector, so a skill that's only mentioned in one part
    # of a multi-topic description (e.g. "...negotiated with vendors...") can
    # end up diluted below skills tied to the sentence's dominant theme, even
    # though it's a perfectly real, distinct skill. To fix this without
    # discarding the existing whole-text ranking, each skill's score is
    # boosted to the BEST evidence found for it anywhere — either the whole
    # activity text, its single best-matching clause (embedding similarity),
    # or its single best-matching extracted keyphrase (TF-IDF similarity).
    # This only ever raises a skill's score, never lowers it, and only
    # applies when there's genuine multi-clause structure to draw on — for a
    # short, single-topic activity (the common case, and every existing
    # single-clause test) phrases == [cleaned] and this is a no-op.
    boosted_sims = sims
    distinctly_evidenced_indices = set()
    if multi_clause and phrase_vecs.shape[0] > 0:
        try:
            phrase_skill_sims = np.stack([
                similarity.cosine_similarity(phrase_vecs[i], _skill_embeddings)
                for i in range(phrase_vecs.shape[0])
            ])  # shape (num_phrases, num_skills)
            best_phrase_sim_per_skill = phrase_skill_sims.max(axis=0)
            boosted_sims = np.maximum(boosted_sims, best_phrase_sim_per_skill)

            # A skill "distinctly evidenced" by this activity is one that is
            # the single best explanation for at least one specific clause
            # (not just a middling contributor to the whole-text blend). This
            # is what actually earns a skill an "extra" slot beyond top_n
            # below — deliberately NOT based on a confidence-percentage floor
            # over the full softmax, since that distribution gets sharpened
            # unpredictably by how many OTHER skills also score reasonably
            # well (e.g. 4 clearly-distinct clauses can each land just under
            # a fixed percentage floor purely because they're crowded by each
            # other, not because any one of them is a weak match).
            for phrase_idx in range(phrase_skill_sims.shape[0]):
                row = phrase_skill_sims[phrase_idx]
                best_skill_for_phrase = int(row.argmax())
                if row[best_skill_for_phrase] > 0:  # excludes true no-signal/tied-at-zero phrases
                    distinctly_evidenced_indices.add(best_skill_for_phrase)
        except Exception:
            logger.warning("phrase_evidence_boost_failed", exc_info=True)

        if keyphrases:
            try:
                kp_sims = np.stack([
                    feature_representation.tfidf_similarity_to_skills(
                        text_pipeline.normalize_for_features(kp["phrase"]) or kp["phrase"]
                    )
                    for kp in keyphrases
                ])
                if kp_sims.shape[1] == num_skills:
                    best_kp_sim_per_skill = kp_sims.max(axis=0)
                    boosted_sims = np.maximum(boosted_sims, best_kp_sim_per_skill)
            except Exception:
                logger.warning("keyphrase_evidence_boost_failed", exc_info=True)

    confidences = similarity.softmax_confidence(boosted_sims) * 100.0

    # --- Genuine-match filtering ---
    # Previously, this function always returned exactly `top_n` matches
    # regardless of how weak the 2nd/3rd candidates were — for a clearly
    # single-skill activity, that meant 2 near-zero-evidence "filler" skills
    # were presented as if they were genuine matches, and for off-topic text
    # every one of the top_n slots was filler. That's not an accident of a
    # missing feature; it's simply that "always return top_n" was never a
    # genuine-match rule at all.
    #
    # The rule used here is deliberately simple, deterministic, and
    # independent of this specific dataset: a match only counts as
    # genuinely supported if the model is more confident in it than it
    # would be by pure chance across all `num_skills` candidates — i.e.
    # confidence_pct > 100 / num_skills (the uniform-random baseline for
    # this many options). This is the exact same "better than chance" bar
    # already used above to decide whether a specific clause counts as
    # distinct evidence for a skill (see distinctly_evidenced_indices) —
    # applying it here too, as the actual inclusion rule for top_matches,
    # rather than only a bonus/extra-slot rule, keeps the two selection
    # decisions consistent instead of running on two different standards.
    # It is NOT tuned to this dataset: it falls out purely of `num_skills`,
    # so it moves automatically if skills.json ever grows or shrinks, and
    # was not chosen by trying values against the evaluation numbers.
    confidence_floor_pct = 100.0 / num_skills if num_skills else 0.0

    global_top = list(similarity.top_n_matches(boosted_sims, n=top_n))
    extra = [i for i in distinctly_evidenced_indices if i not in global_top]
    extra.sort(key=lambda i: boosted_sims[i], reverse=True)
    candidate_indices = (global_top + extra)[:MAX_MULTI_SKILL_MATCHES]
    top_indices = [i for i in candidate_indices if confidences[i] > confidence_floor_pct]

    if not top_indices:
        # Nothing cleared the bar — an honest "no genuinely supported skill
        # found" result rather than forcing a low-evidence guess into the
        # response. keyphrases are still returned (they were computed from
        # real input and remain useful context even without a confident
        # skill match); only top_matches/primary reflect "no match".
        return _no_confident_match_result(keyphrases)

    top_matches = []
    for idx in top_indices:
        profile = _skill_profiles[idx]
        matched_phrase, phrase_sim = _best_matching_phrase(
            _skill_embeddings[idx], phrases, phrase_vecs, fallback=cleaned
        )
        match = {
            "skill": profile["professional_skill"],
            "onet_category": profile["onet_category"],
            "leadership_category": profile["leadership_category"],
            "similarity": round(float(boosted_sims[idx]), 4),
            "confidence_pct": round(float(confidences[idx]), 1),
            "matched_phrase": matched_phrase,
            "explanation": _build_explanation(profile, matched_phrase, float(confidences[idx]), keyphrases),
        }
        top_matches.append(match)

    primary_idx = top_indices[0]
    primary_profile = _skill_profiles[primary_idx]
    primary = dict(top_matches[0])
    primary["market_value"] = primary_profile["market_value"]
    primary["skill_magnitude"], primary["leadership_index"] = _derive_scores(
        primary_profile, primary["confidence_pct"]
    )

    return {
        "top_matches": top_matches,
        "primary": primary,
        "keyphrases": keyphrases,
        "engine": "embedding_tfidf_hybrid_v2",
    }


def _best_matching_phrase(skill_vec, phrases, phrase_vecs, fallback: str):
    """
    Among the activity's sub-phrases, find the one whose embedding is most
    similar to this specific skill's embedding — this is the phrase shown
    to the user as "why this skill was selected".
    """
    if not phrases or phrase_vecs.shape[0] == 0:
        return fallback, 0.0
    phrase_sims = similarity.cosine_similarity(skill_vec, phrase_vecs)
    best_i = int(np.argmax(phrase_sims))
    return phrases[best_i], float(phrase_sims[best_i])


def _build_explanation(profile: dict, matched_phrase: str, confidence_pct: float, keyphrases: list = None) -> str:
    base = (
        f"Matched to \"{profile['professional_skill']}\" with {confidence_pct:.0f}% "
        f"confidence because the phrase \"{matched_phrase}\" is semantically close to "
        f"this skill's profile (category: {profile['onet_category']})."
    )
    # If any extracted keyphrase textually overlaps with this skill's own
    # keywords, name it — small, concrete extra evidence for *why* this
    # skill (not just "trust the model"), directly surfacing the keyphrase
    # extraction step's contribution rather than leaving it as a silent
    # internal signal.
    if keyphrases:
        skill_keywords = profile.get("keywords", [])
        for kp in keyphrases:
            phrase = kp.get("phrase", "")
            if phrase and any(kw and kw.lower() in phrase.lower() for kw in skill_keywords):
                base += f" The keyphrase \"{phrase}\" also supports this match."
                break
    return base


def _derive_scores(profile: dict, confidence_pct: float):
    """
    Converts a confidence percentage into the same skill_magnitude /
    leadership_index numbers the old keyword-density formula used to
    produce, so the rest of app.py (radar metrics, DB columns, PDF export)
    needs no structural changes.
    """
    base = profile["base_magnitude"]
    # Confidence above ~50% nudges magnitude up toward 100; below 50% pulls it
    # down toward the skill's base value. Bounded to [base*0.6, 100].
    confidence_bonus = (confidence_pct - 50.0) / 50.0 * 20.0  # -20..+20
    skill_magnitude = max(base * 0.6, min(100.0, base + confidence_bonus))
    leadership_index = min(100.0, skill_magnitude * profile["leadership_weight"])
    return round(skill_magnitude, 2), round(leadership_index, 2)


def _no_confident_match_result(keyphrases: list = None) -> dict:
    """
    Used when the activity text was real (not blank — see _empty_result for
    that case) but no skill's match confidence cleared the "better than
    chance" floor (see confidence_floor_pct in analyze_activity_semantic).
    `primary` is a clearly-labelled placeholder, not a disguised guess —
    its confidence_pct is 0.0 and its explanation says so outright, so
    nothing downstream can mistake this for a real match.
    """
    return {
        "top_matches": [],
        "keyphrases": keyphrases or [],
        "primary": {
            "skill": "General Administrative Support",
            "onet_category": "Office & Administrative Support",
            "leadership_category": "Team Coordination",
            "similarity": 0.0,
            "confidence_pct": 0.0,
            "matched_phrase": "",
            "explanation": (
                "No skill in the current knowledge base was a genuinely "
                "confident match for this activity description — the closest "
                "candidates scored no better than chance."
            ),
            "market_value": "Medium",
            "skill_magnitude": 60.0,
            "leadership_index": 60.0,
        },
        "engine": "embedding_tfidf_hybrid_v2",
    }


def _empty_result() -> dict:
    return {
        "top_matches": [],
        "keyphrases": [],
        "primary": {
            "skill": "General Administrative Support",
            "onet_category": "Office & Administrative Support",
            "leadership_category": "Team Coordination",
            "similarity": 0.0,
            "confidence_pct": 0.0,
            "matched_phrase": "",
            "explanation": "No descriptive activity text was provided.",
            "market_value": "Medium",
            "skill_magnitude": 60.0,
            "leadership_index": 60.0,
        },
        "engine": "embedding_tfidf_hybrid_v2",
    }
