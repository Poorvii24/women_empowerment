"""
nlp/keyphrase_extractor.py
=============================
Keyphrase Extraction (NLP syllabus Unit V: "Information Extraction ...
Keyphrase Extraction, Implementing KPE").

Pipeline:
    1. Candidate generation — POS-pattern noun-phrase chunking
       (nlp/text_pipeline.extract_noun_phrases): cheap, dependency-free,
       and precise enough for short activity-description sentences.
    2. Candidate ranking — each candidate phrase is scored by how much
       TF-IDF weight it carries against the skill-profile corpus
       (nlp/feature_representation.py). A phrase that is both frequent in
       the user's text AND rare/distinctive across the skill corpus (or
       matches a skill's own vocabulary closely) ranks higher.

This is a real, working implementation of classical keyphrase extraction —
not a call to the embedding engine and not an LLM prompt. It is used to (a)
surface "what specific words drove this match" for explainability, and (b)
optionally cross-check the primary embedding-based skill match in
skill_matcher.py.
"""
import logging

from . import feature_representation, text_pipeline

logger = logging.getLogger("isis.nlp.keyphrase_extractor")


def extract_keyphrases(raw_text: str, top_k: int = 5) -> list[dict]:
    """
    Returns up to `top_k` keyphrases from `raw_text`, ranked by TF-IDF
    weight against the fitted skill corpus:

        [{"phrase": "household budget", "score": 0.42}, ...]

    Never raises: any failure in POS tagging or TF-IDF scoring degrades to
    an empty list rather than breaking the caller (skill_matcher.py already
    treats keyphrases as a purely additive/explanatory output).
    """
    if not raw_text or not raw_text.strip():
        return []

    try:
        candidates = text_pipeline.extract_noun_phrases(raw_text)
    except Exception:
        logger.warning("keyphrase_candidate_generation_failed", exc_info=True)
        return []

    if not candidates:
        return []

    if not feature_representation.is_fitted():
        # No TF-IDF corpus available yet (e.g. skill_matcher hasn't loaded) —
        # return candidates in POS-detection order with a neutral score
        # rather than silently dropping them.
        return [{"phrase": c, "score": 0.0} for c in candidates[:top_k]]

    scored = []
    try:
        for phrase in candidates:
            # Score against the LEMMATIZED form of the phrase, since the TF-IDF
            # corpus itself was fit on lemmatized skill-profile text (see
            # skill_matcher._ensure_loaded) — scoring the raw surface form
            # ("savings") against a lemmatized vocabulary ("saving") would
            # silently miss real matches. The phrase shown to the user stays
            # in its original, readable surface form.
            normalized_phrase = text_pipeline.normalize_for_features(phrase) or phrase
            sims = feature_representation.tfidf_similarity_to_skills(normalized_phrase)
            score = float(sims.max()) if sims.size else 0.0
            scored.append({"phrase": phrase, "score": round(score, 4)})
    except Exception:
        logger.warning("keyphrase_scoring_failed", exc_info=True)
        return [{"phrase": c, "score": 0.0} for c in candidates[:top_k]]

    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:top_k]
