"""
config.py
=========
Environment-based configuration (Task 8 of the production-readiness pass).

This formalizes the configuration ISIS already reads from environment
variables (see app.py's get_secret_key() / validate_environment() / the
app.config.update(...) block) into explicit classes, so it's obvious at a
glance what's configurable and what each environment's defaults are.

IMPORTANT: this module does not change any existing runtime behavior. Every
default here matches exactly what app.py already did before this file
existed — it's a formalization, not a behavior change. app.py can adopt it
gradually (see `select_config()` at the bottom) without breaking anything if
it isn't adopted at all yet.
"""

import os
import secrets
from datetime import timedelta


class BaseConfig:
    """Settings shared by every environment."""

    # --- Core Flask ---
    # SECRET_KEY is intentionally NOT set here with a hardcoded fallback.
    # See `resolve_secret_key()` below — production must supply one via env.
    SECRET_KEY = None

    # --- i18n ---
    # Kept in sync with app.config['BABEL_SUPPORTED_LOCALES'] in app.py (the
    # value actually used at runtime). Only locales with a complete,
    # compiled translation catalog under translations/<locale>/ belong here.
    BABEL_DEFAULT_LOCALE = "en"
    BABEL_SUPPORTED_LOCALES = ["en", "hi", "kn"]

    # --- Session / cookie hardening ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get("SESSION_TIMEOUT_MINUTES", "60")))
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_DURATION = timedelta(days=int(os.environ.get("REMEMBER_COOKIE_DAYS", "14")))

    # --- CSRF ---
    WTF_CSRF_TIME_LIMIT = int(os.environ.get("CSRF_TIME_LIMIT_SECONDS", "3600"))

    # --- Rate limiting ---
    RATELIMIT_DEFAULT = ["200 per day", "50 per hour"]
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # --- Database ---
    # SQLite remains the default persistence layer (unchanged). DATABASE_URL
    # is read here so a future Postgres-backed repository implementation has
    # a single place to look — see docs/ARCHITECTURE.md "Database" section
    # for why a full dual-backend migration wasn't done in this pass.
    SQLITE_DB_PATH = os.environ.get("ISIS_DB_PATH", "isis_portfolio.db")
    DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{SQLITE_DB_PATH}")

    # --- Third-party keys (never hardcoded; missing keys degrade gracefully) ---
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

    # --- Logging ---
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    LOG_DIR = os.environ.get("ISIS_LOG_DIR", "logs")
    LOG_TO_FILE = os.environ.get("ISIS_LOG_TO_FILE", "true").lower() == "true"

    DEBUG = False
    TESTING = False


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False


class TestingConfig(BaseConfig):
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False  # simplifies test-client requests; production keeps CSRF on
    RATELIMIT_ENABLED = False  # avoid flaky tests due to rate limits
    SQLITE_DB_PATH = os.environ.get("ISIS_TEST_DB_PATH", ":memory:")
    LOG_TO_FILE = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


_CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def resolve_secret_key(env_name: str, logger=None):
    """
    Matches app.py's original get_secret_key() behavior exactly:
    - Use ISIS_SECRET_KEY or SECRET_KEY if set.
    - Raise in production if neither is set.
    - Otherwise generate a temporary per-process key and warn.
    """
    secret_key = os.environ.get("ISIS_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if secret_key:
        return secret_key
    if env_name == "production":
        raise RuntimeError("ISIS_SECRET_KEY must be set in production.")
    if logger:
        logger.warning("ISIS_SECRET_KEY is not set; using a temporary development-only key.")
    return secrets.token_urlsafe(32)


def select_config(logger=None):
    """
    Returns the Config class for the current ISIS_ENV / FLASK_ENV, and sets
    its SECRET_KEY. Defaults to 'development' if unset — identical to the
    original app.py behavior of treating anything other than
    FLASK_ENV=production as development-like.
    """
    env_name = (os.environ.get("ISIS_ENV") or os.environ.get("FLASK_ENV") or "development").lower()
    config_cls = _CONFIGS.get(env_name, DevelopmentConfig)
    config_cls.SECRET_KEY = resolve_secret_key(env_name, logger=logger)
    return config_cls, env_name
