"""
tests/test_feature_and_keyphrase.py
=====================================
Unit tests for nlp/feature_representation.py (TF-IDF feature representation)
and nlp/keyphrase_extractor.py (POS-candidate + TF-IDF-ranked keyphrase
extraction).

A small, fixed skill corpus is fitted directly (bypassing skill_matcher.py
and skills.json) so these tests are self-contained and don't depend on the
real skill catalog or the embedding engine.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from nlp import feature_representation, keyphrase_extractor

_CORPUS = [
    "Financial Management. Budgeting, tracking expenses, and savings planning.",
    "Training and Mentoring. Teaching, tutoring, and coaching others.",
    "Healthcare Coordination. Patient care, medication, and checkups for elders.",
]


@pytest.fixture(autouse=True)
def _reset_and_fit_corpus():
    """Fit a small deterministic corpus before every test, and reset state after."""
    feature_representation._vectorizer = None
    feature_representation._skill_tfidf_matrix = None
    feature_representation._fitted_corpus_key = None
    feature_representation.fit_skill_corpus(_CORPUS)
    yield
    feature_representation._vectorizer = None
    feature_representation._skill_tfidf_matrix = None
    feature_representation._fitted_corpus_key = None


class TestFeatureRepresentation:

    def test_is_fitted_after_fit(self):
        assert feature_representation.is_fitted() is True

    def test_is_fitted_false_before_any_fit(self):
        feature_representation._vectorizer = None
        feature_representation._fitted_corpus_key = None
        assert feature_representation.is_fitted() is False

    def test_similarity_shape_matches_corpus_size(self):
        sims = feature_representation.tfidf_similarity_to_skills("budget savings")
        assert sims.shape[0] == len(_CORPUS)

    def test_similarity_ranks_relevant_document_highest(self):
        sims = feature_representation.tfidf_similarity_to_skills("budget savings expenses")
        assert int(sims.argmax()) == 0  # the Financial Management doc

    def test_similarity_empty_query_returns_zeros(self):
        sims = feature_representation.tfidf_similarity_to_skills("")
        assert sims.shape[0] == len(_CORPUS)
        assert all(s == 0 for s in sims)

    def test_similarity_unfitted_returns_zero_length_array(self):
        feature_representation._vectorizer = None
        feature_representation._skill_tfidf_matrix = None
        sims = feature_representation.tfidf_similarity_to_skills("budget")
        assert sims.shape[0] == 0

    def test_top_terms_returns_in_vocabulary_words(self):
        terms = feature_representation.top_terms("budget savings expenses", top_k=3)
        assert len(terms) > 0
        assert all(isinstance(t, str) for t in terms)

    def test_top_terms_empty_query_returns_empty_list(self):
        assert feature_representation.top_terms("") == []

    def test_refitting_same_corpus_is_a_noop(self):
        first_vectorizer = feature_representation._vectorizer
        feature_representation.fit_skill_corpus(_CORPUS)
        assert feature_representation._vectorizer is first_vectorizer


class TestKeyphraseExtractor:

    def test_extract_keyphrases_returns_ranked_list(self):
        result = keyphrase_extractor.extract_keyphrases(
            "I managed the monthly household budget and tracked savings carefully.", top_k=5
        )
        assert isinstance(result, list)
        assert all("phrase" in kp and "score" in kp for kp in result)
        scores = [kp["score"] for kp in result]
        assert scores == sorted(scores, reverse=True)

    def test_extract_keyphrases_empty_text_returns_empty_list(self):
        assert keyphrase_extractor.extract_keyphrases("") == []
        assert keyphrase_extractor.extract_keyphrases("   ") == []

    def test_extract_keyphrases_respects_top_k(self):
        result = keyphrase_extractor.extract_keyphrases(
            "I managed the monthly household budget, taught my kids math, "
            "and took care of my elderly parent's medication schedule.",
            top_k=2,
        )
        assert len(result) <= 2

    def test_extract_keyphrases_unfitted_corpus_still_returns_candidates(self):
        feature_representation._vectorizer = None
        feature_representation._skill_tfidf_matrix = None
        result = keyphrase_extractor.extract_keyphrases("I managed the household budget carefully.")
        assert isinstance(result, list)
        # unfitted -> neutral zero scores, but candidates should still surface
        assert all(kp["score"] == 0.0 for kp in result)
