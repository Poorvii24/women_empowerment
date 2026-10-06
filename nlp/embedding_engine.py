"""
nlp/embedding_engine.py
=========================
Thin, lazy-loading wrapper around a single SentenceTransformer model
(all-MiniLM-L6-v2 by default).

Why a wrapper instead of calling SentenceTransformer directly everywhere:
    1. LAZY LOAD — the ~90MB model is only loaded into memory the first time
       `encode()` is actually called, not at Flask import time. This keeps
       `python app.py` startup fast even when Gemini is being used for every
       request and the local model is never touched.
    2. SINGLETON — the model is loaded exactly once per process and reused
       for every request afterwards (loading it per-request would add
       ~1-2 seconds of dead time to every single activity analysis).
    3. THREAD-SAFE — a lock guards the first load so two concurrent requests
       on app startup can't both trigger a duplicate model load.
    4. SWAPPABLE — tests (and skill_matcher.py's offline mode) can inject a
       fake encoder via `set_encoder_override()` without needing the real
       model or network access, which matters here because the real model is
       downloaded from Hugging Face Hub on first use and the sandbox this was
       built in has no route to huggingface.co.
"""
import logging
import threading

logger = logging.getLogger("isis.nlp.embedding_engine")

MODEL_NAME = "all-MiniLM-L6-v2"   # 384-dim sentence embeddings, ~90MB, fast on CPU
EMBEDDING_DIM = 384

_model = None
_model_lock = threading.Lock()
_encoder_override = None  # used only by tests / offline mode


def set_encoder_override(fn):
    """
    Inject a stand-in encoder function: fn(list[str]) -> np.ndarray of shape
    (len(texts), EMBEDDING_DIM). Used by the test suite to exercise the rest
    of the pipeline (similarity, ranking, caching) without downloading or
    running the real transformer model. Pass None to clear the override and
    return to the real model.
    """
    global _encoder_override
    _encoder_override = fn


def _load_model():
    """
    Loads the SentenceTransformer model once, guarded by a lock.

    Tries the local cache first (local_files_only=True), which makes zero
    network calls. This matters because SentenceTransformer's default load
    path does an online HEAD request to huggingface.co on every load — even
    when the model is already cached — to check for a newer revision. On a
    slow or unreachable connection that turns into repeated timeouts with
    exponential backoff (multiple files, up to ~5 retries each), which can
    take minutes and was surfacing as "Skill gap analysis failed" / 500
    errors in the Career Hub and Professional Portfolio PDF.

    Falls back to the normal online path only if nothing is cached yet
    (e.g. genuinely the first run on a machine), so the very first load
    still works exactly as before.
    """
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is None:  # re-check inside the lock (another thread may have won the race)
            logger.info("nlp_model_loading", extra={"model": MODEL_NAME})
            # Imported here (not at module top) so importing this module never
            # requires sentence-transformers/torch to be installed unless the
            # real model path is actually used (e.g. pure unit tests with a mock).
            from sentence_transformers import SentenceTransformer
            try:
                _model = SentenceTransformer(MODEL_NAME, local_files_only=True)
                logger.info("nlp_model_loaded_from_cache", extra={"model": MODEL_NAME})
            except Exception:
                logger.info("nlp_model_cache_miss_downloading", extra={"model": MODEL_NAME})
                _model = SentenceTransformer(MODEL_NAME)
                logger.info("nlp_model_loaded_from_network", extra={"model": MODEL_NAME})
    return _model


def encode(texts: list[str]):
    """
    Encode a list of strings into normalized embedding vectors.

    Returns a numpy array of shape (len(texts), EMBEDDING_DIM), L2-normalized
    so that cosine similarity reduces to a plain dot product downstream
    (similarity.py relies on this).

    Empty input returns an empty (0, EMBEDDING_DIM) array rather than raising,
    so callers don't need to special-case "no phrases to embed".
    """
    import numpy as np

    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype="float32")

    if _encoder_override is not None:
        return _encoder_override(texts)

    model = _load_model()
    # normalize_embeddings=True -> unit vectors, so similarity.py can use a
    # plain dot product instead of a full cosine-similarity computation.
    return model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )


def is_model_loaded() -> bool:
    """Returns True if the real model has already been loaded into memory."""
    return _model is not None
