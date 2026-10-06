"""
nlp/feature_representation.py
================================
Classical "Converting Text to Features" stage (NLP syllabus Unit III):
TF-IDF vectorization + cosine similarity, used as a lexical/statistical
grounding signal alongside the transformer-embedding engine.

Why this exists alongside embedding_engine.py rather than instead of it:
    - Embeddings (nlp/embedding_engine.py) capture semantic meaning and
      generalize well ("looked after my elderly mother" ~ "healthcare"
      even with zero shared words).
    - TF-IDF captures exact lexical overlap and is fully explainable —
      useful when a user's wording directly matches a skill's own
      keywords ("budget", "savings"), and it's the feature-representation
      technique this NLP course covers, so it's implemented for real here
      rather than just describing it.

skill_matcher.py fits ONE TfidfVectorizer over the corpus of skill profile
texts (the same texts embedded by embedding_engine.py) and reuses it for
every request — fit cost is paid once, not per activity.
"""
import logging

import numpy as np

logger = logging.getLogger("isis.nlp.feature_representation")

_vectorizer = None
_skill_tfidf_matrix = None
_fitted_corpus_key = None


class FeatureRepresentationError(Exception):
    """Raised only for programming errors (e.g. calling similarity before fit)."""


def fit_skill_corpus(skill_texts: list[str], normalized_skill_texts: list[str] | None = None):
    """
    Fits (or refits, if the corpus changed) a TF-IDF vectorizer over the
    skill profile corpus. `normalized_skill_texts` — pre-lemmatized,
    stopword-free text from nlp/text_pipeline.normalize_for_features — is
    preferred when available since it matches what user activity text is
    normalized to before comparison; falls back to raw `skill_texts` if not
    supplied (e.g. from a caller that hasn't computed normalization).
    """
    global _vectorizer, _skill_tfidf_matrix, _fitted_corpus_key

    corpus = normalized_skill_texts if normalized_skill_texts else skill_texts
    corpus_key = hash(tuple(corpus))
    if _vectorizer is not None and corpus_key == _fitted_corpus_key:
        return  # already fitted for this exact corpus

    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),   # unigrams + bigrams — captures short skill phrases
        min_df=1,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(corpus)

    _vectorizer = vectorizer
    _skill_tfidf_matrix = matrix
    _fitted_corpus_key = corpus_key
    logger.info("tfidf_corpus_fitted", extra={"num_docs": len(corpus), "vocab_size": len(vectorizer.vocabulary_)})


def is_fitted() -> bool:
    return _vectorizer is not None


def tfidf_similarity_to_skills(query_text: str) -> np.ndarray:
    """
    Returns a 1D array of cosine similarities between `query_text` and every
    skill in the fitted corpus, in the same order the corpus was fitted.
    Returns an all-zero array (never raises) if the vectorizer hasn't been
    fitted yet or the query is empty — callers should treat that as "no
    lexical signal available" and rely on the embedding score alone.
    """
    if _vectorizer is None or not query_text:
        num_skills = _skill_tfidf_matrix.shape[0] if _skill_tfidf_matrix is not None else 0
        return np.zeros((num_skills,), dtype="float32")

    from sklearn.metrics.pairwise import cosine_similarity as sk_cosine_similarity

    query_vec = _vectorizer.transform([query_text])
    sims = sk_cosine_similarity(query_vec, _skill_tfidf_matrix)[0]
    return sims.astype("float32")


def top_terms(query_text: str, top_k: int = 5) -> list[str]:
    """
    Returns the `top_k` highest-TF-IDF-weight terms/bigrams in `query_text`
    according to the fitted vocabulary — a simple, explainable summary of
    "which words in what the user typed actually carried weight".
    Returns [] if unfitted or the query produced no in-vocabulary terms.
    """
    if _vectorizer is None or not query_text:
        return []
    try:
        query_vec = _vectorizer.transform([query_text])
        row = query_vec.tocoo()
        if row.nnz == 0:
            return []
        feature_names = _vectorizer.get_feature_names_out()
        pairs = sorted(zip(row.col, row.data), key=lambda p: p[1], reverse=True)[:top_k]
        return [feature_names[i] for i, _ in pairs]
    except Exception:
        logger.warning("tfidf_top_terms_failed", exc_info=True)
        return []
