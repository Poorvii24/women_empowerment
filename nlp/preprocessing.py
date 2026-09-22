"""
nlp/preprocessing.py
=====================
Lightweight text preparation for the embedding pipeline.

SentenceTransformer models are robust to raw natural language, so this module
intentionally does NOT do aggressive NLP preprocessing (no stemming, no
stopword removal, no lowercasing-only-then-losing-meaning) — that kind of
normalization is exactly what breaks the *old* keyword-regex engine and is
unnecessary (and often harmful) for transformer-based sentence embeddings,
which are trained on natural, unprocessed text.

What this module DOES do:
    1. clean_text()      – strip control characters, collapse whitespace,
                            remove URLs — basic input hygiene only.
    2. extract_phrases()  – split an activity description into smaller
                            clause-level chunks (including plain list-style
                            commas, e.g. "did X, did Y, did Z and did W").
                            Used for EXPLAINABILITY (which specific phrase
                            matched a skill) AND, in skill_matcher.py, as
                            additional per-clause evidence so a multi-topic
                            activity description can surface more than one
                            distinct matched skill instead of only the single
                            best match for the whole blended sentence.
"""
import re

_URL_RE = re.compile(r"https?://\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Clause-level splitters: sentence punctuation, conjunctions used as connectors,
# and commas. Kept simple and dependency-free (no spaCy/nltk) by design —
# this is a cheap segmentation step, not a parser.
#
# Order matters: the comma+connector alternative is listed BEFORE the bare
# comma alternative so a comma followed by "and"/"but"/etc. still has that
# connector word consumed (stripped) exactly as before; the bare-comma
# alternative only kicks in for commas NOT already handled by the more
# specific pattern. This was added because plain list-style enumeration
# ("I did X, did Y, did Z and did W") previously didn't split at all — a
# comma had to be immediately followed by one of a handful of connector
# words to count as a clause boundary, so a whole multi-task sentence like
# "I managed expenses, planned budgets, negotiated with vendors, organized
# events and taught my children" stayed as a single unsplit phrase, which
# in turn meant skill_matcher.py could only ever compare ONE blended
# embedding of the entire sentence against each skill — diluting or hiding
# any skill that wasn't the single dominant theme of the whole sentence.
_CLAUSE_SPLIT_RE = re.compile(
    r"[.!?;]+"
    r"|\,\s+(?:and|but|then|so|while|after|before)\b"
    r"|\,\s+"
    r"|\band\s+then\b",
    flags=re.IGNORECASE,
)


def clean_text(text: str) -> str:
    """
    Minimal input hygiene before embedding:
      - strip control characters
      - remove bare URLs (rare in this app's input, but defensive)
      - collapse repeated whitespace
      - trim leading/trailing whitespace

    Deliberately preserves case, punctuation, and word order — the embedding
    model relies on these for meaning.
    """
    if not text:
        return ""
    text = _CONTROL_CHARS_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def extract_phrases(text: str, min_words: int = 3) -> list[str]:
    """
    Split an activity description into clause-level phrases for
    phrase-level explainability matching.

    Example:
        "I managed the household budget, and I also taught my kids math"
        -> ["I managed the household budget", "I also taught my kids math"]

    Phrases shorter than `min_words` words are dropped (too short to carry
    standalone semantic meaning, e.g. a stray "and so" fragment).
    If splitting produces nothing usable, the whole cleaned text is
    returned as a single-element list so callers always have at least
    one phrase to compare against.
    """
    cleaned = clean_text(text)
    if not cleaned:
        return []

    raw_chunks = _CLAUSE_SPLIT_RE.split(cleaned)
    phrases = []
    for chunk in raw_chunks:
        chunk = chunk.strip(" ,;")
        if not chunk:
            continue
        if len(chunk.split()) >= min_words:
            phrases.append(chunk)

    return phrases if phrases else [cleaned]
