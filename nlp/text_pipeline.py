"""
nlp/text_pipeline.py
=====================
Classical NLP preprocessing stages (NLP syllabus Unit I/II/V):

    tokenize()            - word tokenization (NLTK Treebank tokenizer)
    remove_stopwords()    - stopword filtering
    pos_tag_tokens()      - Part-of-Speech tagging (averaged perceptron tagger)
    lemmatize()           - POS-aware WordNet lemmatization
    extract_noun_phrases()- POS-pattern candidate generation for keyphrase
                            extraction (JJ*NN+ chunks), the standard first
                            step of a keyphrase-extraction pipeline

This module sits BETWEEN nlp/preprocessing.py (basic text hygiene: whitespace,
URLs, control chars) and nlp/keyphrase_extractor.py / nlp/skill_matcher.py.
It is intentionally separate from the embedding pipeline (embedding_engine.py
still receives raw cleaned text — SentenceTransformer models are trained on
natural, unlemmatized text and perform worse on it). This module exists to
produce the tokens/lemmas/candidate-phrases used for the classical,
syllabus-required feature-representation and keyphrase-extraction stages.

Robustness: NLTK's tokenizer/tagger/lemmatizer need small downloaded data
packages (punkt, averaged_perceptron_tagger, wordnet, stopwords). On first
use this module tries to download them (from NLTK's own data mirror) and
caches them under the default NLTK data directory. If a machine has no
network access at that moment, every public function here still returns a
usable (if slightly cruder) result via a pure-regex fallback path instead of
raising — this module must never be the reason `/analyze_activity` fails.
"""
import logging
import re
import threading

logger = logging.getLogger("isis.nlp.text_pipeline")

_setup_lock = threading.Lock()
_nltk_ready = False
_nltk_unavailable = False  # set True after a failed setup attempt so we don't retry every call

# Minimal built-in stopword fallback (used only if NLTK's stopword corpus
# can't be loaded) — enough to keep noun-phrase/keyphrase extraction sane.
_FALLBACK_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "of", "to",
    "in", "on", "at", "for", "with", "about", "as", "by", "is", "are",
    "was", "were", "be", "been", "being", "i", "you", "he", "she", "it",
    "we", "they", "my", "our", "your", "his", "her", "its", "their",
    "this", "that", "these", "those", "also", "than", "too", "very",
    "do", "does", "did", "have", "has", "had", "can", "will", "would",
    "could", "should", "just", "not", "no",
}

_WORD_RE = re.compile(r"[A-Za-z']+")


def _ensure_nltk_ready() -> bool:
    """
    Lazily downloads the small NLTK data packages this module needs, once
    per process. Returns True if NLTK (tokenizer + tagger + lemmatizer +
    stopwords) is usable, False if unavailable (caller should use the
    regex fallback path). Never raises.
    """
    global _nltk_ready, _nltk_unavailable
    if _nltk_ready:
        return True
    if _nltk_unavailable:
        return False

    with _setup_lock:
        if _nltk_ready:
            return True
        if _nltk_unavailable:
            return False
        try:
            import nltk
            required = [
                ("tokenizers/punkt_tab", "punkt_tab"),
                ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
                ("corpora/stopwords", "stopwords"),
                ("corpora/wordnet", "wordnet"),
                ("corpora/omw-1.4", "omw-1.4"),
            ]
            for find_path, pkg in required:
                try:
                    nltk.data.find(find_path)
                except LookupError:
                    nltk.download(pkg, quiet=True)
            # Verify the pieces we actually depend on can be constructed.
            from nltk.corpus import stopwords, wordnet  # noqa: F401
            from nltk import pos_tag, word_tokenize
            word_tokenize("warm-up sentence")
            pos_tag(["warm", "up"])
            _nltk_ready = True
            logger.info("nltk_pipeline_ready")
            return True
        except Exception:
            logger.warning("nltk_pipeline_unavailable_using_regex_fallback", exc_info=True)
            _nltk_unavailable = True
            return False


def tokenize(text: str) -> list[str]:
    """Word-tokenizes `text`. Falls back to a regex word-splitter if NLTK is unavailable."""
    if not text:
        return []
    if _ensure_nltk_ready():
        from nltk import word_tokenize
        try:
            return word_tokenize(text)
        except Exception:
            logger.warning("nltk_word_tokenize_failed_falling_back", exc_info=True)
    return _WORD_RE.findall(text)


def _stopword_set() -> set:
    if _ensure_nltk_ready():
        try:
            from nltk.corpus import stopwords
            return set(stopwords.words("english"))
        except Exception:
            logger.warning("nltk_stopwords_unavailable_using_fallback", exc_info=True)
    return _FALLBACK_STOPWORDS


def remove_stopwords(tokens: list[str]) -> list[str]:
    """Filters out stopwords and non-alphabetic tokens (punctuation, numbers)."""
    stop = _stopword_set()
    return [t for t in tokens if t.isalpha() and t.lower() not in stop]


def pos_tag_tokens(tokens: list[str]) -> list[tuple]:
    """
    Returns [(token, POS_tag), ...] using NLTK's averaged perceptron tagger.
    Falls back to tagging everything "NN" (noun) if NLTK is unavailable —
    crude, but keeps extract_noun_phrases() from failing outright.
    """
    if not tokens:
        return []
    if _ensure_nltk_ready():
        from nltk import pos_tag
        try:
            return pos_tag(tokens)
        except Exception:
            logger.warning("nltk_pos_tag_failed_falling_back", exc_info=True)
    return [(t, "NN") for t in tokens]


_WORDNET_POS_MAP = {
    "J": "a",   # adjective
    "V": "v",   # verb
    "N": "n",   # noun
    "R": "r",   # adverb
}


def lemmatize(tokens: list[str], pos_tags: list[tuple] | None = None) -> list[str]:
    """
    POS-aware lemmatization via WordNet (e.g. "managing" -> "manage",
    "children" -> "child"). Falls back to a light suffix-stripping stemmer
    (not a real Porter stemmer, just common English suffixes) if the
    WordNet corpus can't be loaded, so callers always get *some*
    normalization rather than an exception.
    """
    if not tokens:
        return []

    if _ensure_nltk_ready():
        try:
            from nltk.stem import WordNetLemmatizer
            lemmatizer = WordNetLemmatizer()
            tags = pos_tags if pos_tags is not None else pos_tag_tokens(tokens)
            tag_map = {tok: tag for tok, tag in tags}
            lemmas = []
            for tok in tokens:
                wn_pos = _WORDNET_POS_MAP.get(tag_map.get(tok, "N")[0], "n")
                lemmas.append(lemmatizer.lemmatize(tok.lower(), pos=wn_pos))
            return lemmas
        except Exception:
            logger.warning("nltk_lemmatize_failed_falling_back", exc_info=True)

    return [_naive_stem(t.lower()) for t in tokens]


def _naive_stem(word: str) -> str:
    """Last-resort suffix stripping used only if WordNet is unavailable."""
    for suffix in ("ing", "edly", "ies", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def extract_noun_phrases(text: str, max_phrase_len: int = 4) -> list[str]:
    """
    Candidate keyphrase generation using a POS-pattern chunker:
    contiguous runs of (adjective|noun)* noun tokens, e.g.
    "monthly household budget" (JJ JJ NN) or "elderly parent" (JJ NN).

    This is the standard candidate-generation step of a keyphrase-extraction
    pipeline (NLP syllabus Unit V) — candidates are ranked afterwards by
    nlp/keyphrase_extractor.py using TF-IDF, not here.
    """
    tokens = tokenize(text)
    if not tokens:
        return []
    tagged = pos_tag_tokens(tokens)

    phrases = []
    current = []
    for tok, tag in tagged:
        is_candidate_pos = tag.startswith("JJ") or tag.startswith("NN")
        is_word = tok.isalpha()
        if is_candidate_pos and is_word:
            current.append(tok)
        else:
            if current:
                phrases.append(current)
            current = []
    if current:
        phrases.append(current)

    stop = _stopword_set()
    result = []
    seen = set()
    for chunk in phrases:
        # Trim leading/trailing stopword-like single letters, cap length
        chunk = chunk[:max_phrase_len]
        if not chunk or all(w.lower() in stop for w in chunk):
            continue
        phrase = " ".join(chunk).lower()
        if len(phrase) < 3 or phrase in seen:
            continue
        seen.add(phrase)
        result.append(phrase)
    return result


def normalize_for_features(text: str) -> str:
    """
    Full normalization pipeline used as the input to TF-IDF feature
    representation (nlp/feature_representation.py): tokenize -> drop
    stopwords/punctuation -> POS-aware lemmatize -> rejoin.

    Deliberately NOT used as input to the embedding engine — see the module
    docstring for why.
    """
    tokens = tokenize(text)
    tagged = pos_tag_tokens(tokens)
    content_tokens = [(t, p) for t, p in tagged if t.isalpha() and t.lower() not in _stopword_set()]
    if not content_tokens:
        return ""
    toks, tags = zip(*content_tokens)
    lemmas = lemmatize(list(toks), list(zip(toks, tags)))
    return " ".join(lemmas)
