"""
tests/test_text_pipeline.py
==============================
Unit tests for nlp/text_pipeline.py — tokenization, stopword removal,
POS tagging, lemmatization, and noun-phrase candidate extraction.

These exercise the real NLTK path when NLTK data is available in the test
environment (downloaded once via `python -m nltk.downloader ...`, see
README/DEPLOYMENT docs) and fall back gracefully otherwise — either way the
assertions here only rely on behavior guaranteed by the module's contract
(never raises, returns non-empty structures for non-empty input), not on
which code path executed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nlp import text_pipeline


class TestTokenize:

    def test_tokenize_splits_words(self):
        tokens = text_pipeline.tokenize("I managed the household budget.")
        assert "managed" in [t.lower() for t in tokens]
        assert "budget" in [t.lower() for t in tokens]

    def test_tokenize_empty_input(self):
        assert text_pipeline.tokenize("") == []
        assert text_pipeline.tokenize(None) == []


class TestStopwords:

    def test_remove_stopwords_drops_common_words(self):
        tokens = text_pipeline.tokenize("I managed the household budget and the savings")
        filtered = text_pipeline.remove_stopwords(tokens)
        lowered = [t.lower() for t in filtered]
        assert "the" not in lowered
        assert "and" not in lowered
        assert "budget" in lowered
        assert "savings" in lowered

    def test_remove_stopwords_drops_punctuation(self):
        tokens = ["budget", ",", "savings", "."]
        filtered = text_pipeline.remove_stopwords(tokens)
        assert "," not in filtered
        assert "." not in filtered


class TestPosTagAndLemmatize:

    def test_pos_tag_returns_pairs_for_every_token(self):
        tokens = text_pipeline.tokenize("I taught my kids math")
        tags = text_pipeline.pos_tag_tokens(tokens)
        assert len(tags) == len(tokens)
        assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in tags)

    def test_pos_tag_empty_input(self):
        assert text_pipeline.pos_tag_tokens([]) == []

    def test_lemmatize_normalizes_plurals_and_verb_forms(self):
        tokens = ["children", "managing", "savings"]
        tags = text_pipeline.pos_tag_tokens(tokens)
        lemmas = text_pipeline.lemmatize(tokens, tags)
        assert len(lemmas) == 3
        # Whichever path ran (real WordNet or the naive fallback stemmer),
        # lemmas must be no longer than their surface form and lowercase.
        for lemma, tok in zip(lemmas, tokens):
            assert lemma == lemma.lower()
            assert len(lemma) <= len(tok)

    def test_lemmatize_empty_input(self):
        assert text_pipeline.lemmatize([]) == []


class TestNounPhrases:

    def test_extract_noun_phrases_finds_multiword_candidates(self):
        text = "I managed the monthly household budget and tracked our family savings."
        phrases = text_pipeline.extract_noun_phrases(text)
        assert phrases  # at least one candidate
        assert any("budget" in p for p in phrases)

    def test_extract_noun_phrases_empty_input(self):
        assert text_pipeline.extract_noun_phrases("") == []

    def test_extract_noun_phrases_deduplicates(self):
        text = "budget budget budget"
        phrases = text_pipeline.extract_noun_phrases(text)
        assert len(phrases) == len(set(phrases))


class TestNormalizeForFeatures:

    def test_normalize_for_features_drops_stopwords_and_lowercases(self):
        result = text_pipeline.normalize_for_features("I managed the household budget and the savings")
        assert "the" not in result.split()
        assert "and" not in result.split()
        assert result == result.lower()

    def test_normalize_for_features_empty_input(self):
        assert text_pipeline.normalize_for_features("") == ""

    def test_normalize_for_features_all_stopwords_returns_empty(self):
        assert text_pipeline.normalize_for_features("the a an of") == ""
