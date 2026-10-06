"""
app.py - Main Flask application for the ISIS (Invisible Skill Intelligence System) backend.

Endpoints:
    POST /analyze_activity     - Accept a raw activity text and return mapped professional skills
    GET  /dashboard_metrics    - Return aggregated skill metrics for the dashboard charts
    GET  /activities           - List past recorded activities for a user
    GET  /health               - Health check
"""
import datetime
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import math
from collections import OrderedDict, Counter
import urllib.parse
from datetime import timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()  # No-op if no .env file exists; never overrides real env vars already set
except ImportError:
    pass  # python-dotenv is optional — env vars can still be set directly (e.g. in CI/containers)

from flask import (
    Flask, request, jsonify, send_file,
    render_template, redirect, url_for, flash, session, abort, has_request_context
)
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError, validate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_babel import Babel, _
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from wtforms.validators import ValidationError
from google import genai
from google.genai import types
from fpdf import FPDF
import db
import config
from repositories.user_repository import UserRepository
from repositories.copilot_repository import CopilotRepository
from utils import validators

user_repository = UserRepository()
copilot_repository = CopilotRepository()
from nlp import skill_matcher

# Phase 4 — Career Intelligence Platform services
from services import (
    role_taxonomy,
    resume_parser,
    skill_gap_engine,
    scoring_engine,
    learning_recommender,
    growth_tracker,
    opportunity_recommender,
    ats_engine,
    pdf_design,
    ai_copilot,
)


class JsonLogFormatter(logging.Formatter):
    """Format application logs as compact JSON records, including any custom `extra=` fields."""

    # Standard attributes every LogRecord has — anything else on the record
    # was added via logger.info("...", extra={...}) and should be surfaced.
    _STANDARD_ATTRS = set(logging.LogRecord(
        "", 0, "", 0, "", (), None
    ).__dict__.keys()) | {"message", "asctime"}

    def format(self, record):
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if has_request_context():
            payload.update({
                "path": request.path,
                "method": request.method,
                "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
            })
        # Surface any caller-supplied structured context (e.g. extra={"user_id": ...})
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class _KeywordFilter(logging.Filter):
    """Routes log records to a dedicated file based on logger name or event
    keywords, without requiring any change to the ~150 existing logger.info/
    warning/exception call sites throughout the app."""

    def __init__(self, logger_prefixes=(), message_keywords=()):
        super().__init__()
        self.logger_prefixes = logger_prefixes
        self.message_keywords = message_keywords

    def filter(self, record):
        if self.logger_prefixes and any(record.name.startswith(p) for p in self.logger_prefixes):
            return True
        if self.message_keywords:
            msg = record.getMessage().lower()
            return any(kw in msg for kw in self.message_keywords)
        return False


def configure_logging():
    """Configure structured application logging once at startup.

    Keeps the original console StreamHandler exactly as before (so existing
    log-watching/deployment tooling that reads stdout is unaffected), and
    additionally writes rotating log files (Task 9): a general app log, an
    errors-only log, a security-events log (auth/CSRF/rate-limit), and an
    AI-inference log (Gemini calls, embedding/NLP pipeline) — all optional
    via ISIS_LOG_TO_FILE, off by default in tests.
    """
    formatter = JsonLogFormatter()
    root = logging.getLogger()
    root.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

    if os.environ.get("ISIS_LOG_TO_FILE", "true").lower() != "true":
        return

    log_dir = os.environ.get("ISIS_LOG_DIR", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        logging.getLogger("isis").warning("log_dir_create_failed", extra={"log_dir": log_dir})
        return

    def rotating(filename, level=logging.INFO, max_bytes=5_000_000, backups=5):
        h = RotatingFileHandler(os.path.join(log_dir, filename), maxBytes=max_bytes, backupCount=backups)
        h.setFormatter(formatter)
        h.setLevel(level)
        return h

    app_handler = rotating("app.log")
    root.addHandler(app_handler)

    error_handler = rotating("error.log", level=logging.ERROR)
    root.addHandler(error_handler)

    security_handler = rotating("security.log")
    security_handler.addFilter(_KeywordFilter(
        message_keywords=("csrf", "login", "auth", "rate_limit", "unauthorized", "session")
    ))
    root.addHandler(security_handler)

    ai_handler = rotating("ai_inference.log")
    ai_handler.addFilter(_KeywordFilter(
        logger_prefixes=("isis.nlp", "isis.ai_copilot"),
        message_keywords=("gemini", "embedding", "nlp_model"),
    ))
    root.addHandler(ai_handler)


configure_logging()
logger = logging.getLogger("isis")


def get_secret_key():
    """Load the Flask secret key without keeping a hardcoded fallback in source.

    Delegates to config.resolve_secret_key() (see config.py) — same exact
    resolution order (ISIS_SECRET_KEY, then SECRET_KEY, then a temporary
    dev-only key with a warning, raising in production if none is set).
    Accepts the new optional ISIS_ENV var in addition to FLASK_ENV; anyone
    not setting ISIS_ENV sees identical behavior to before.
    """
    env_name = (os.environ.get("ISIS_ENV") or os.environ.get("FLASK_ENV") or "development").lower()
    return config.resolve_secret_key(env_name, logger=logger)


def validate_environment():
    """Validate required runtime configuration and log actionable startup messages."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        logger.warning("GEMINI_API_KEY is not set; activity analysis will use the local fallback path.")
    elif not gemini_key.startswith("AIza"):
        logger.warning(
            "GEMINI_API_KEY looks invalid (expected 'AIza...' format). "
            "Get a valid key at https://aistudio.google.com/apikey"
        )
    if not os.environ.get("ISIS_SECRET_KEY") and not os.environ.get("SECRET_KEY"):
        logger.warning("Set ISIS_SECRET_KEY before running outside local development.")


# Serve static files (styles.css, script.js) from the current directory
app = Flask(__name__, static_folder=".", static_url_path="",
            template_folder=".")  # serve HTML templates via render_template
app.secret_key = get_secret_key()
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
# Only languages with a complete, human-reviewed translation catalog are
# listed here. Previously this listed 7 locales ('ta', 'te', 'mr', 'bn'
# included) while only 'en'/'hi'/'kn' had any translations at all — that
# silently served English to anyone who picked one of the other 4 "supported"
# languages. Rather than promise 7 languages and deliver 3, this app now
# only declares the 3 that are genuinely, fully translated. Add a locale
# here only once its full messages.po catalog exists and is compiled.
app.config['BABEL_SUPPORTED_LOCALES'] = ['en', 'hi', 'kn']
# Use an absolute path so translations are found regardless of the working
# directory Flask was started from. static_folder="." makes root_path the cwd
# at startup, which can differ from the project directory in some launchers.
app.config['BABEL_TRANSLATION_DIRECTORIES'] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'translations'
)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=int(os.environ.get("SESSION_TIMEOUT_MINUTES", "60"))),
    WTF_CSRF_TIME_LIMIT=int(os.environ.get("CSRF_TIME_LIMIT_SECONDS", "3600")),
    # "Remember me" cookie (flask-login) gets the same hardening as the session cookie,
    # plus its own bounded lifetime so a stolen device doesn't grant indefinite access.
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    REMEMBER_COOKIE_DURATION=timedelta(days=int(os.environ.get("REMEMBER_COOKIE_DAYS", "14"))),
)
csrf = CSRFProtect(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)
validate_environment()

# ---------------------------------------------------------------------------
# Flask-Babel Setup
# ---------------------------------------------------------------------------
def get_locale():
    # Always prefer the explicit user session choice.
    # Never fall back to Accept-Language — that would override the user's toggle.
    return session.get('lang', 'en')

babel = Babel(app, locale_selector=get_locale)

# ---------------------------------------------------------------------------
# Language-switch URL builders
# ---------------------------------------------------------------------------

def build_job_link(job_role: str) -> str:
    """Returns a LinkedIn job-search URL for the given role."""
    query = urllib.parse.quote_plus(job_role.strip())
    return f"https://www.linkedin.com/jobs/search/?keywords={query}"


def build_learning_link(growth_skill: str) -> str:
    """Returns a YouTube search URL for learning the given skill."""
    query = urllib.parse.quote_plus(f"learn {growth_skill.strip()} for beginners")
    return f"https://www.youtube.com/results?search_query={query}"

# ---------------------------------------------------------------------------
# Flask-Login Setup
# ---------------------------------------------------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"          # redirect to /login when @login_required fails
login_manager.login_message = "Please sign in to access your portfolio."
login_manager.login_message_category = "error"


class User(UserMixin):
    """Lightweight User model wrapping our db dict."""
    def __init__(self, user_dict):
        self.id = str(user_dict["id"])
        self.username = user_dict["username"]

    @staticmethod
    def get(user_id):
        row = db.get_user_by_id(int(user_id))
        return User(row) if row else None


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


def authenticated_user_id() -> str:
    """Return the current Flask-Login user id for user-scoped database queries."""
    if not current_user.is_authenticated:
        abort(401)
    return str(current_user.get_id())


def is_safe_redirect(target: str) -> bool:
    """Allow redirects only to this application's host."""
    if not target:
        return False
    ref_url = urllib.parse.urlparse(request.host_url)
    test_url = urllib.parse.urlparse(urllib.parse.urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def validate_pdf_csrf_token():
    """Require a CSRF token for the GET-based PDF download endpoint."""
    try:
        validate_csrf(request.args.get("csrf_token", ""))
    except ValidationError:
        logger.warning("pdf_csrf_validation_failed", extra={"user_id": getattr(current_user, "id", None)})
        abort(400)


@app.before_request
def refresh_session_timeout():
    """Apply the configured permanent-session timeout to authenticated browser sessions."""
    session.permanent = True


@app.after_request
def set_security_headers(response):
    """
    Adds standard security headers to every response (Task 6). Additive only
    — doesn't change any response body, status code, or existing header.
    CSP is deliberately permissive enough to allow the CDN scripts/styles
    this app already loads (Bootstrap, Chart.js, bootstrap-icons,
    highlight.js) rather than breaking them; tightening it further would
    require self-hosting those assets, which is out of scope for this pass.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if app.config.get("SESSION_COOKIE_SECURE"):
        # Only sent when the app is actually configured for HTTPS (production) —
        # setting this over plain HTTP in development would be misleading.
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    logger.warning("csrf_validation_failed")
    message = _("That took a little too long — please refresh the page and try again.")
    if request.is_json or request.path.startswith("/analyze_activity"):
        return jsonify({"status": "error", "message": message}), 400
    flash(message, "error")
    return redirect(url_for("login"))


@app.errorhandler(429)
def handle_rate_limit(error):
    logger.warning("rate_limit_exceeded")
    message = _("You're moving fast! Please wait a moment and try again.")
    if request.is_json or request.path.startswith("/analyze_activity"):
        return jsonify({"status": "error", "message": message}), 429
    flash(message, "error")
    return redirect(request.referrer or url_for("index"))


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        return error
    logger.exception("unexpected_application_error")
    message = _("Something didn't work on our end — please try again.")
    if request.is_json or request.path.startswith("/analyze_activity"):
        return jsonify({"status": "error", "message": message}), 500
    flash(message, "error")
    return redirect(url_for("index") if current_user.is_authenticated else url_for("login"))

# Initialize Gemini Client
# A valid Google AI Studio key starts with "AIza". Keys with other prefixes
# (e.g. "AQ.", OAuth tokens) are structurally invalid and will always return
# 400 INVALID_ARGUMENT, so we detect and skip them here rather than letting
# every request fail with a confusing error. Setting client=None causes the
# embedding-only fallback path to be used automatically.
_raw_gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
_gemini_key_looks_valid = bool(_raw_gemini_key)

client = None
if _gemini_key_looks_valid:
    try:
        client = genai.Client(api_key=_raw_gemini_key)
    except Exception:
        logger.exception("gemini_client_initialization_failed")
        client = None
elif _raw_gemini_key:
    # Key is set but has the wrong format — log once at startup so the operator
    # knows, without spamming every request.
    logger.warning(
        "gemini_api_key_invalid_format",
        extra={
            "hint": "Google AI Studio keys start with 'AIza'. "
                    "Get a valid key at https://aistudio.google.com/apikey"
        }
    )

# Load the professional skill reference dataset once at startup
SKILLS_PATH = os.path.join(os.path.dirname(__file__), "skills.json")
try:
    with open(SKILLS_PATH, "r", encoding="utf-8") as f:
        SKILL_DATA = json.load(f)
    SKILL_MAPPINGS = SKILL_DATA["skill_mappings"]
    LEADERSHIP_CATEGORIES = SKILL_DATA["leadership_categories"]
except FileNotFoundError:
    logger.critical("skills_reference_file_missing", extra={"path": SKILLS_PATH})
    raise RuntimeError(
        f"Required skills reference file not found at {SKILLS_PATH}. "
        "ISIS cannot start without it."
    )
except (json.JSONDecodeError, KeyError) as e:
    logger.critical("skills_reference_file_invalid", extra={"path": SKILLS_PATH, "error": str(e)})
    raise RuntimeError(
        f"skills.json is malformed or missing required keys ({e}). "
        "ISIS cannot start without a valid skills reference file."
    )


# ---------------------------------------------------------------------------
# Analytics Engine - Zero-Shot Semantic Keyword Mapping
# ---------------------------------------------------------------------------

def compute_employability_score(metrics: dict) -> float:
    """
    Computes an overall employability score from aggregated SQL metrics.
    Formula: weighted average of category magnitudes scaled by activity count.
    """
    breakdown = metrics.get("category_breakdown", [])
    if not breakdown:
        return 0.0

    total_weighted = 0.0
    total_weight = 0.0
    for cat in breakdown:
        weight = LEADERSHIP_CATEGORIES.get(cat["leadership_category"], {}).get("weight", 1.0)
        total_weighted += cat["avg_magnitude"] * weight * cat["count"]
        total_weight += weight * cat["count"]

    raw_score = total_weighted / total_weight if total_weight > 0 else 0.0
    # Scale to a 0-100 score – cap at 100
    return min(100, round(raw_score, 2))


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = db.get_user_by_username(username)
        if row and check_password_hash(row["password_hash"], password):
            user = User(row)
            login_user(user, remember=True)
            logger.info("login_success", extra={"username": username, "user_id": user.id})
            next_page = request.args.get("next")
            return redirect(next_page if is_safe_redirect(next_page) else url_for("index"))
        logger.warning("login_failed", extra={"username": username})
        flash(_("We couldn't find an account with that username and password. Please double-check and try again."), "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")
        # Validation
        if not username or len(username) < 3:
            flash(_("Please use a username with at least 3 letters or numbers."), "error")
        elif not re.match(r'^[a-zA-Z0-9_]+$', username):
            flash(_("Usernames can only have letters, numbers, and underscores — no spaces or symbols."), "error")
        elif len(password) < 8:
            flash(_("Please choose a password with at least 8 characters."), "error")
        elif password != confirm:
            flash(_("Those two passwords don't match — please try typing them again."), "error")
        else:
            pw_hash = generate_password_hash(password)
            user_id = db.create_user(username, pw_hash)
            if user_id is None:
                logger.warning("registration_failed_duplicate_username", extra={"username": username})
                flash(_("Someone's already using that username — please try a different one."), "error")
            else:
                logger.info("registration_success", extra={"username": username, "user_id": user_id})
                flash(_("You're all set! Please sign in to get started."), "success")
                return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash(_("You've been signed out. See you next time!"), "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Health Check (Docker HEALTHCHECK / CI startup verification / load balancers)
# ---------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    """
    Unauthenticated liveness + readiness check. Verifies the database is
    reachable (the one dependency that must work for the app to be useful)
    without touching the Gemini API or the embedding model, since those are
    allowed to be degraded/unavailable per the existing graceful-fallback
    design elsewhere in this app.
    """
    try:
        db.get_connection().close()
        db_ok = True
    except Exception:
        logger.exception("healthz_db_check_failed")
        db_ok = False
    status_code = 200 if db_ok else 503
    return jsonify({
        "status": "ok" if db_ok else "error",
        "database": "ok" if db_ok else "unreachable",
        "gemini_configured": client is not None,
    }), status_code


# ---------------------------------------------------------------------------
# API Documentation (Task 12)
# ---------------------------------------------------------------------------

@app.route("/api/openapi.yaml")
def api_openapi_spec():
    """Serves the hand-written OpenAPI 3.0 spec documenting every route."""
    return send_file(
        os.path.join(os.path.dirname(__file__), "docs", "openapi.yaml"),
        mimetype="application/yaml",
    )


@app.route("/api/docs")
def api_docs():
    """Swagger UI, loaded from a CDN (no new project dependency), pointed at
    /api/openapi.yaml. Unauthenticated by design — API documentation isn't
    sensitive, and requiring login here would be an odd first experience for
    anyone evaluating the API."""
    return """<!DOCTYPE html>
<html>
<head>
  <title>ISIS API Documentation</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.17.14/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.17.14/swagger-ui-bundle.min.js"></script>
  <script>
    window.onload = () => SwaggerUIBundle({ url: "/api/openapi.yaml", dom_id: "#swagger-ui" });
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------



@app.route("/")
@login_required
def index():
    """Serves the main frontend dashboard."""
    # Render the root template directly so Babel tags are evaluated.
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    """Simple health check endpoint."""
    return jsonify({"status": "OK", "message": "ISIS backend is running."}), 200


@app.route("/analyze_activity", methods=["POST"])
@login_required
@limiter.limit("6 per minute")
@limiter.limit("40 per day")
def analyze_activity():
    """
    POST /analyze_activity
    Request Body (JSON):
        {
            "activity": "I managed the household budget and planned weekly meals",
        }

    Returns a high-precision JSON for Chart.js frontend including:
        - radar_metrics: dict with 5 skill dimensions (0-100)
        - career_equivalency: storytelling job title match
        - leadership_index, employability_score: numeric scores
        - skills_mapped: list of keyword badges
        - resume_snippet: AI-generated bullet
    """
    # Safety: initialise all variables that may be referenced in except/finally branches
    raw_learning = {}

    body = request.get_json(silent=True) or {}
    user_input = body.get("activity", "").strip()
    user_id = authenticated_user_id()

    if not user_input or len(user_input) < 5:
        return jsonify({"status": "error", "message": _("Please tell us a little more about what you did — even a sentence or two helps.")}), 400

    # NOTE: GEMINI_API_KEY is intentionally OPTIONAL here. If it's not set, the
    # Gemini call below is skipped entirely and the embedding-based NLP engine
    # (nlp/skill_matcher.py) drives the whole analysis on its own — this is a
    # fully supported "offline mode", not a degraded error state.

    # -------------------------------------------------------------------------
    # HYBRID AI PIPELINE — Step 1: Embedding-based skill extraction.
    # Runs unconditionally and BEFORE Gemini, so:
    #   (a) it's available as a fast, deterministic fallback if Gemini's call
    #       fails for any reason, and
    #   (b) it can independently ground/cross-check Gemini's own scoring
    #       below ("Result Fusion") even when Gemini succeeds.
    # This never raises — analyze_activity_semantic() degrades gracefully
    # rather than breaking the whole request if the NLP engine has an issue.
    # -------------------------------------------------------------------------
    try:
        semantic_result = skill_matcher.analyze_activity_semantic(user_input, top_n=3)
        nlp_error_detail = None
    except Exception as e:
        logger.exception("semantic_skill_extraction_failed", extra={"user_id": user_id})
        semantic_result = skill_matcher.analyze_activity_semantic("")  # safe, returns a generic low-confidence result
        # Surfaced to the UI explanation text below — e.g. "ModuleNotFoundError" means
        # `pip install -r requirements.txt` hasn't been (successfully) re-run since
        # sentence-transformers was added; "OSError"/"ConnectionError" usually means the
        # model couldn't be downloaded from Hugging Face Hub (network/firewall).
        nlp_error_detail = f"{type(e).__name__}: {str(e)[:200]}"

    # Small, defensive summary of the local NLP pipeline's output, used only
    # to ground the Gemini prompt with real extracted signal (never raises —
    # falls back to empty/neutral values if the shape is ever unexpected).
    semantic_primary_skill_for_prompt = semantic_result.get("primary", {}).get("skill", "Unknown")
    semantic_primary_conf_for_prompt = semantic_result.get("primary", {}).get("confidence_pct", 0)
    semantic_keyphrases_for_prompt = ", ".join(
        kp.get("phrase", "") for kp in semantic_result.get("keyphrases", [])[:5] if kp.get("phrase")
    ) or "none extracted"

    # Read language directly from session — more reliable than get_locale() in AJAX context
    # get_locale() can fall back to browser Accept-Language on AJAX requests.
    lang = session.get('lang', 'en')
    lang_map = {
        'en': 'English',
        'hi': 'Hindi (हिंदी)',
        'kn': 'Kannada (ಕನ್ನಡ)'
    }
    target_language = lang_map.get(lang, 'English')

    # -------------------------------------------------------------------------
    # The High-Precision Gemini Prompt
    # -------------------------------------------------------------------------
    prompt = f"""
You are a professional career analyst specializing in translating unpaid and informal labor
into corporate-standard credentials. Analyze the following activity and return a precise JSON.

🌐 LANGUAGE MANDATE — APPLY IMMEDIATELY:
The user's interface language is **{target_language}**.
Return `job_role`, `startup_idea`, and `growth_skill` in **{target_language}** only.
If {target_language} is Hindi (हिंदी): write those fields entirely in हिंदी script.
If {target_language} is Kannada (ಕನ್ನಡ): write those fields entirely in ಕನ್ನಡ script.
If {target_language} is English: write in English.

IMPORTANT MULTI-LANGUAGE INSTRUCTION — READ THIS FIRST: 
The user's selected language is **{target_language}**. You MUST generate the following fields in **{target_language}**:
  - `professional_title`, `career_equivalency`, `resume_bullet`, `mapped_skill`
  - ALL items inside `skills_mapped`
  - `market_opportunities.startup_idea` — translate the business concept name and description
  - `market_opportunities.startup_budget` — keep the ₹ amount as-is, translate only the description suffix
  - `market_opportunities.collaboration_match` — translate the partnership suggestion
  - `market_opportunities.job_role` — CRITICAL: Translate the professional job title to the most accurate local term in {target_language}. The JSON key MUST remain exactly `"job_role"`.
  - `market_opportunities.growth_skill` (the upskilling recommendation label)
  - ALL `title` and `desc` fields inside `business_roadmap`
  - `pitch_email.subject` and `pitch_email.body`
  - ALL `why_it_fits` and `action_step` fields in `matches`
  - ALL `title` fields in `matches`

If {target_language} is **Hindi (हिंदी)** or **Kannada (ಕನ್ನಡ)**:
  - Use simple, everyday rural/semi-urban India vocabulary. AVOID formal or academic terminology.
  - Job titles may be kept in English if no good local equivalent exists, but add a 2-word local descriptor.
  - The JSON **keys** must ALWAYS stay in English regardless of language.

CAREER EQUIVALENCY LOGIC:
Instead of a fixed title, you MUST select a corporate role for the `career_equivalency` field based on the input's complexity. Base your decision on the number of people managed and the total budget/resources handled:
  * **Low Complexity** (e.g., daily chores, no budget) -> "Administrative Assistant"
  * **Medium Complexity** (e.g., budget planning, event coordination, small teams) -> "Operations Coordinator" or "Project Lead"
  * **High Complexity** (e.g., managing community funds, leading large teams, crisis mediation) -> "Operations Manager" or "Strategic Resource Analyst"

OPPORTUNITY ENGINE LOGIC:
Based on ONLY the user's ACTUAL activity input (which could be healthcare, finance, childcare, education, agriculture, crafts, etc.), you MUST suggest three HYPER-SPECIFIC and CONTEXTUALLY ACCURATE opportunities. You are FORBIDDEN from generating generic or catering-related responses unless the user explicitly mentions cooking or food.

CRITICAL DEMO DATA MAPPING:
To ensure perfect demonstration, you MUST follow these exact mappings if the user's input matches the domain.
IMPORTANT: Even for these hardcoded concepts, you MUST STILL translate all text values into {target_language}:
  * If the input is Health-related: Use "Public Health Outreach Coordinator" as the BASE title for `job_role`, then translate it into {target_language}. Use "Mobile Health & First-Aid Training Center" as the BASE for `startup_idea`, then translate it.
  * If the input is Logistics-related: Use "Supply Chain Coordinator" as the BASE title for `job_role`, then translate it into {target_language}. Use "Village-to-City Agri-Logistics Service" as the BASE for `startup_idea`, then translate it.

For all other domains:
  * **Startup Idea**: A micro-business concept directly tied to the domain they described (e.g., if finance → "Micro-savings coaching group")
  * **Collaboration Match**: A partnership idea uniquely suited to the domain they described.
  * **Job Role**: You MUST map their unpaid/informal labor to a legitimate, high-value professional title. For example, managing a 300-person health camp should map to "Logistics Coordinator" or "Public Health Manager". It must reflect the true scale of their work, stripped of "household" stigma.

**Regional Context Rule**: If `{target_language}` is Hindi or Kannada, the ideas MUST be culturally and regionally localized to rural/semi-urban India.
UPSKILLING RECOMMENDATION LOGIC:
Based on the matched roles, recommend one immediately actionable upskilling step.
  * **Skill to Learn**: A specific, high-ROI skill (e.g., "Advanced Excel" or "Digital Marketing")
  * **Free Resource**: A specific free learning platform/video (e.g., "YouTube: Excel for Business" or "Coursera: Intro to Management")
  * **Daily Goal**: A micro-habit (e.g., "Watch a 10-minute video today")

SMART MATCH ENGINE LOGIC:
You MUST also suggest exactly 2 unique **career Smart Matches** based on the specific combination of skills demonstrated. Each Smart Match must be:
  * A direct, actionable job title or entrepreneurial role (e.g., "Catering Business Lead", "Logistics Coordinator", "Community Budget Analyst")
  * Assigned a **match_percentage** (an integer, 60–99) reflecting how well the user's demonstrated skills align with that role
  * Accompanied by a short, one-sentence **why_it_fits** (e.g., "Your experience coordinating 10+ people maps directly to team leadership roles.")
  * Include a **action_step** — one concrete first step (e.g., "Join the National Skill Development Corporation (NSDC) portal to register your catering skills.")
  * These two matches MUST be different from each other and from the `specific_job_roles` in `market_opportunities`.
  
SCORING & METRICS LOGIC (NEW 8-POINT DATA):
You are receiving detailed, 8-point data from the user including Time Spent, Supplies Managed, Target Audience, and Conflict Handling Approach. You MUST use this deep context to generate a highly accurate `leadership_index`, `employability_score`, and `radar_metrics`. For example: 
  * If the user managed large budgets or complex supplies, boost the "Financial" and "Strategic" radar metrics.
  * If the user mediated conflicts effectively, heavily boost the "Crisis" and "Emotional" radar metrics.
  * If they coordinated large audiences/beneficiaries over long time periods, their `employability_score` should reflect high-level project management (85+).

Activity Data: "{user_input}"

Local NLP Pipeline Signal (extracted independently via tokenization, POS-tagging,
lemmatization, keyphrase extraction, and TF-IDF/embedding skill matching — use
this ONLY as grounding context, not as something to quote verbatim):
  * Top matched skill: {semantic_primary_skill_for_prompt} (confidence: {semantic_primary_conf_for_prompt}%)
  * Extracted keyphrases: {semantic_keyphrases_for_prompt}

Return ONLY a valid JSON object with exactly these keys:
{{
  "professional_title":   "<e.g., Strategic Resource Coordinator>",
  "career_equivalency":   "<The matched title from the Complexity Logic above>",
  "resume_bullet":        "<A high-impact, metric-forward sentence like: Led cross-functional household logistics for 4 stakeholders, achieving 20% reduction in discretionary spend>",
  "leadership_index":     <integer 1-100>,
  "employability_score":  <integer 1-100>,
  "skills_mapped":        ["<Keyword 1>", "<Keyword 2>", "<Keyword 3>"],
  "onet_category":        "<e.g., Business & Financial Operations>",
  "leadership_category":  "<One of: Decision Making | Resource Allocation | Strategic Planning | Team Coordination | Team Development | Empathy & Crisis Management>",
  "industry":             "<The core industry of their input, e.g., Healthcare, Food, Logistics, Childcare>",
  "radar_metrics": {{
    "Strategic":  <integer 1-100>,
    "Financial":  <integer 1-100>,
    "Crisis":     <integer 1-100>,
    "Team":       <integer 1-100>,
    "Emotional":  <integer 1-100>
  }},
  "market_opportunities": {{
    "startup_idea":        "<A micro-business concept based on their skills>",
    "startup_budget":      "<Realistic estimated startup cost in INR, e.g. '₹5,000 – ₹15,000' for micro-businesses or '₹50,000 – ₹1,00,000' for service businesses>",
    "collaboration_match": "<A partnership opportunity>",
    "job_role":            "<A relatable target job role>",
    "business_roadmap": [
      {{ "step": 1, "title": "<e.g., Licensing & Legal>", "desc": "<Short action step>" }},
      {{ "step": 2, "title": "<e.g., Service Pricing>", "desc": "<Short action step>" }},
      {{ "step": 3, "title": "<e.g., Local Outreach>", "desc": "<Short action step>" }}
    ],
    "pitch_email": {{
      "subject": "<A professional, domain-specific subject line>",
      "body": "<A brief 2-sentence pitch proposing a partnership, excluding the greeting and signoff>"
    }}
  }},
  "matches": [
    {{
      "title":            "<Career Smart Match #1, e.g., Catering Business Lead>",
      "match_percentage": <integer 60-99>,
      "why_it_fits":      "<One-sentence reason this role fits their demonstrated skills>",
      "action_step":      "<One concrete first step to pursue this role>"
    }},
    {{
      "title":            "<Career Smart Match #2, different from #1>",
      "match_percentage": <integer 60-99>,
      "why_it_fits":      "<One-sentence reason this role fits their demonstrated skills>",
      "action_step":      "<One concrete first step to pursue this role>"
    }}
  ]
}}

Rules:
- All numeric values must be integers between 1 and 100.
- radar_metrics values must reflect the actual skills evident in the activity.
- career_equivalency must sound like a real job title in the corporate world.
- Return ONLY the JSON. No markdown fences, no commentary.

⚠️  ABSOLUTE FINAL MANDATE — THIS OVERRIDES EVERYTHING ABOVE:
The output language is {target_language}. The following fields MUST be written in {target_language} and ONLY {target_language}. No exceptions, no mixing with English:
  • market_opportunities.job_role
  • market_opportunities.startup_idea
  • market_opportunities.collaboration_match
  • market_opportunities.growth_skill
  • ALL business_roadmap title and desc values
  • ALL matches title, why_it_fits, action_step values
If {target_language} is **Hindi (हिंदी)**: write in हिंदी script.
If {target_language} is **Kannada (ಕನ್ನಡ)**: write in ಕನ್ನಡ script.
The JSON keys themselves stay in English always.
"""

    # -------------------------------------------------------------------------
    # Validation helper — ensures all 5 radar values are Chart.js-safe
    # -------------------------------------------------------------------------
    def validate_and_clamp(val, default=50):
        """Clamps a value to integer 1–100, or returns default on failure."""
        try:
            return max(1, min(100, int(float(val))))
        except (TypeError, ValueError):
            return default

    parsed_result = {}
    gemini_ok = False
    gemini_error_detail = None

    if not _raw_gemini_key:
        gemini_error_detail = (
            "Gemini not configured (GEMINI_API_KEY not set) — running in embedding-only mode. "
            "This is expected if you're intentionally running without Gemini."
        )
    elif not _gemini_key_looks_valid:
        gemini_error_detail = (
            "Gemini API key format appears invalid. "
            "Google AI Studio keys start with 'AIza'. "
            "Please update GEMINI_API_KEY in your .env file."
        )
    elif client is None:
        gemini_error_detail = (
            "Gemini client failed to initialize at startup. "
            "Check your API key and server logs."
        )
    else:
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",  # far larger free-tier quota than gemini-2.5-pro
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            parsed_result = json.loads(response.text)
            gemini_ok = True

        except Exception as e:
            logger.warning("gemini_api_call_failed", extra={"error_type": type(e).__name__, "error_message": str(e)})
            # Kept short and exception-type-only by default (never leak full stack traces to the
            # client) — but specific enough that "ModuleNotFoundError" vs "PermissionDenied" vs
            # "ResourceExhausted" tells you immediately whether it's a missing key, quota, or
            # something else, without needing server console access.
            gemini_error_detail = f"{type(e).__name__}: {str(e)[:200]}"

    # -------------------------------------------------------------------------
    # HYBRID AI PIPELINE — Step 3: Result Fusion.
    # Gemini drives the narrative content either way (titles, bullets, startup
    # ideas, smart matches) — that creative/contextual generation is exactly
    # what an LLM is good at and the embedding engine is not. But the two
    # *numeric* scores (leadership_index, employability_score) are blended
    # with the independent embedding-based signal so Gemini isn't the only
    # source of truth for those numbers ("Gemini should enhance the
    # prediction rather than being the only intelligence source").
    # -------------------------------------------------------------------------
    semantic_primary = semantic_result["primary"]

    # How much weight the embedding engine's score gets when blended with
    # Gemini's. Chosen so Gemini's richer, context-aware scoring still leads,
    # while a confident embedding match can meaningfully pull an
    # over/under-confident Gemini score back toward a grounded value.
    EMBEDDING_FUSION_WEIGHT = 0.30

    if gemini_ok:
        mapped_skill        = str(parsed_result.get("professional_title", "General Administration"))
        career_equivalency  = str(parsed_result.get("career_equivalency", "Matches Administrative Coordinator"))
        resume_snippet      = str(parsed_result.get("resume_bullet", f"Demonstrated expertise in {mapped_skill}."))
        skills_mapped       = parsed_result.get("skills_mapped", [])[:5]  # Cap at 5
        onet_category       = str(parsed_result.get("onet_category", "Office & Administrative Support"))
        leadership_category = str(parsed_result.get("leadership_category", "Team Coordination"))

        gemini_leadership_index    = validate_and_clamp(parsed_result.get("leadership_index"), 75)
        gemini_employability_score = validate_and_clamp(parsed_result.get("employability_score"), 75)

        # Fusion: weighted blend of Gemini's score with the embedding engine's
        # independently-derived score for the skill IT matched.
        leadership_index = round(
            gemini_leadership_index * (1 - EMBEDDING_FUSION_WEIGHT)
            + semantic_primary["leadership_index"] * EMBEDDING_FUSION_WEIGHT
        )
        employability_score = round(
            gemini_employability_score * (1 - EMBEDDING_FUSION_WEIGHT)
            + semantic_primary["skill_magnitude"] * EMBEDDING_FUSION_WEIGHT
        )
        fusion_method = "gemini_primary_embedding_grounded"

        # Validate the 5-point radar_metrics dict
        raw_radar = parsed_result.get("radar_metrics", {})
        radar_metrics = {
            "Strategic": validate_and_clamp(raw_radar.get("Strategic"), 50),
            "Financial": validate_and_clamp(raw_radar.get("Financial"), 50),
            "Crisis":    validate_and_clamp(raw_radar.get("Crisis"), 50),
            "Team":      validate_and_clamp(raw_radar.get("Team"), 50),
            "Emotional": validate_and_clamp(raw_radar.get("Emotional"), 50),
        }
    else:
        # Gemini call failed — fall back entirely to the embedding-based
        # semantic match computed in Step 1 above. This REPLACES the old
        # keyword-regex `map_activity_to_skill()` engine (removed in Phase 3).
        mapped_skill         = semantic_primary["skill"]
        career_equivalency   = "Matches Administrative Coordinator"
        # Include a trimmed version of the user's own activity text so every
        # submission produces a unique snippet — prevents the DB dedup (GROUP BY
        # resume_snippet) from collapsing all embedding-only entries into one row
        # and the frontend from skipping all but the first.
        activity_summary = user_input[:120].rstrip() + ("…" if len(user_input) > 120 else "")
        resume_snippet        = f"Applied {mapped_skill} skills: {activity_summary}"
        leadership_index      = validate_and_clamp(semantic_primary["leadership_index"], 70)
        employability_score   = validate_and_clamp(semantic_primary["skill_magnitude"], 70)
        skills_mapped          = []
        onet_category          = semantic_primary["onet_category"]
        leadership_category    = semantic_primary["leadership_category"]
        fusion_method           = "embedding_only_fallback"

        # Derive 5-point radar from category weight (same shape as before,
        # now sourced from the embedding engine's confidence-derived magnitude)
        base = validate_and_clamp(semantic_primary["skill_magnitude"], 60)
        radar_metrics = {
            "Strategic": base if "Strategic" in leadership_category else max(20, base - 20),
            "Financial": base if "Resource" in leadership_category else max(20, base - 25),
            "Crisis":    base if "Crisis" in leadership_category else max(20, base - 30),
            "Team":      base if "Team" in leadership_category or "Decision" in leadership_category else max(20, base - 20),
            "Emotional": base if "Empathy" in leadership_category or "Development" in leadership_category else max(20, base - 25),
        }

    # -------------------------------------------------------------------------
    # Persist all scores to ISIS SQLite DB
    # -------------------------------------------------------------------------
    activity_id = db.insert_activity(
        user_id=user_id,
        input_activity=user_input,
        mapped_skill=mapped_skill,
        onet_category=onet_category,
        leadership_category=leadership_category,
        skill_magnitude=employability_score,
        market_value="High",
        career_equivalency=career_equivalency,
        radar_strategic=radar_metrics["Strategic"],
        radar_financial=radar_metrics["Financial"],
        radar_crisis=radar_metrics["Crisis"],
        radar_team=radar_metrics["Team"],
        radar_emotional=radar_metrics["Emotional"],
        leadership_index=leadership_index,
        employability_score=employability_score,
        skills_mapped=skills_mapped,
        resume_snippet=resume_snippet,
        nlp_primary_skill=semantic_primary["skill"],
        nlp_confidence_pct=semantic_primary["confidence_pct"],
        nlp_similarity_score=semantic_primary["similarity"],
        nlp_matched_phrase=semantic_primary["matched_phrase"],
        fusion_method=fusion_method,
    )

    # -------------------------------------------------------------------------
    # Auto-create a notification from the Opportunity Engine
    # -------------------------------------------------------------------------
    raw_opps = parsed_result.get("market_opportunities", {}) if isinstance(parsed_result, dict) else {}
    if not isinstance(raw_opps, dict):
        raw_opps = {}

    # Extract raw_learning FIRST — used below to build growth_skill
    raw_learning = parsed_result.get("learning_path", {}) if isinstance(parsed_result, dict) else {}
    if not isinstance(raw_learning, dict):
        raw_learning = {}

    # Safely extract roadmap, providing generic fallbacks if AI misses it
    raw_roadmap = raw_opps.get("business_roadmap", [])
    if not isinstance(raw_roadmap, list) or len(raw_roadmap) < 3:
        raw_roadmap = [
            { "step": 1, "title": "Step 1: Licensing & Certifications", "desc": "Register your business legally and secure any local compliance documents required for your specific product/service." },
            { "step": 2, "title": "Step 2: Service/Product Planning",   "desc": "Design your core offering and calculate a competitive pricing model based on a markup of your base operating costs." },
            { "step": 3, "title": "Step 3: Community Outreach",         "desc": "Identify exactly two community channels (e.g., local WhatsApp groups or community boards) to broadcast your launch message." }
        ]

    raw_pitch = raw_opps.get("pitch_email", {})
    if not isinstance(raw_pitch, dict):
        raw_pitch = {}

    # Flatten 5 critical keys — demo fallbacks guarantee non-empty values even on AI failure
    startup_idea_val        = str(raw_opps.get("startup_idea")        or raw_opps.get("startup")       or "Community Wellness Center")
    startup_budget_val      = str(raw_opps.get("startup_budget")      or "₹10,000 – ₹25,000")
    collaboration_match_val = str(raw_opps.get("collaboration_match") or raw_opps.get("collaboration") or "Partner with Local PHC / District Health Office")
    job_role_val            = str(raw_opps.get("job_role")            or raw_opps.get("specific_job_roles") or "Public Health Outreach Coordinator")

    raw_growth_skill = raw_learning.get("skill_to_learn") if isinstance(raw_learning, dict) else None
    growth_skill_val = str(raw_growth_skill or "Digital Marketing")
    learning_url_val = "https://www.youtube.com/embed/Xv1tM_pX22Y"  # verified Google Digital Garage

    market_opps = {
        # flat keys — primary surface area read by script.js
        "startup_idea":        startup_idea_val,
        "startup_budget":      startup_budget_val,
        "collaboration_match": collaboration_match_val,
        "job_role":            job_role_val,
        "growth_skill":        growth_skill_val,
        "learning_url":        learning_url_val,
        # nested extras for business roadmap & pitch modals
        "business_roadmap":    raw_roadmap[:3],
        "pitch_email": {
            "subject": str(raw_pitch.get("subject") or "Partnership Proposal — Community Service Collaboration"),
            "body":    str(raw_pitch.get("body")    or "I have extensive experience coordinating successful community operations and would love to discuss a potential partnership. I specialize in delivering structural results for local teams.")
        }
    }
    smart_matches = parsed_result.get("matches", []) if isinstance(parsed_result, dict) else []

    # Guarantee learning_path is always populated
    learning_path = {
        "skill_to_learn": growth_skill_val,
        "free_resource":  str(raw_learning.get("free_resource")  or "Google Digital Garage on YouTube"),
        "daily_goal":     str(raw_learning.get("daily_goal")     or "Watch a 10-minute video today")
    }

    # Sanitize: keep only the first 2, and ensure required keys exist
    sanitized_matches = []
    seen_titles = set()
    for m in smart_matches[:2]:
        if not isinstance(m, dict):
            continue
        title = str(m.get("title", "")).strip()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        sanitized_matches.append({
            "title":            title,
            "match_percentage": validate_and_clamp(m.get("match_percentage"), 75),
            "why_it_fits":      str(m.get("why_it_fits", "")),
            "action_step":      str(m.get("action_step", ""))
        })

    if market_opps:
        notif_msg = (
            f"🚀 New Opportunity: {market_opps.get('startup_idea', '')} | "
            f"💼 Job: {market_opps.get('specific_job_roles', '')}"
        )
        db.add_notification(user_id=user_id, message=notif_msg, link="/")

    # -------------------------------------------------------------------------
    # Return high-precision Chart.js-ready JSON
    # -------------------------------------------------------------------------
    return jsonify({
        "status":               "success",
        "activity_id":          activity_id,
        "transferable_skill":   mapped_skill,
        "career_equivalency":   career_equivalency,
        "onet_category":        onet_category,
        "leadership_category":  leadership_category,
        "leadership_index":     leadership_index,
        "skill_magnitude":      employability_score,
        "employability_score":  employability_score,
        "market_value":         "High",
        "resume_snippet":       resume_snippet,
        "skills_mapped":        skills_mapped,
        "radar_metrics":        radar_metrics,
        "radar_data_array":     list(radar_metrics.values()),
        "industry":             str(parsed_result.get("industry", "Business")),
        "market_opportunities": market_opps,
        # Flattened top-level keys — guaranteed non-empty for demo
        "startup_idea":         market_opps["startup_idea"],
        "startup_budget":        market_opps.get("startup_budget", "₹10,000 – ₹25,000"),
        "collaboration_match":  market_opps["collaboration_match"],
        "job_role":             market_opps["job_role"],
        "growth_skill":         market_opps["growth_skill"],
        "learning_url":         market_opps["learning_url"],
        # Real external links built from the AI-returned values
        "job_link":             build_job_link(market_opps["job_role"]),
        "learning_link":        build_learning_link(market_opps["growth_skill"]),
        "learning_path":        learning_path,
        "matches":              sanitized_matches,
        "source":               "gemini" if gemini_ok else "local_fallback",
        "fusion_method":        fusion_method,
        # Debug-friendly error detail — null when that engine succeeded.
        # Lets the UI explain *why* a fallback happened instead of just that it did.
        "gemini_error_detail":  gemini_error_detail,
        "nlp_error_detail":     nlp_error_detail,
        # Phase 3 — embedding-based explainability, always present regardless
        # of whether Gemini succeeded (Task 5/6: the embedding signal is
        # computed unconditionally and exposed for every prediction).
        "semantic_analysis":    semantic_result
    }), 201


@app.route("/notifications", methods=["GET"])
@login_required
def get_notifications_route():
    """GET /notifications - Return all unread+recent notifications."""
    notes = db.get_notifications(user_id=current_user.id, limit=10)
    db.mark_all_read(user_id=current_user.id)
    return jsonify({"notifications": notes})


@app.route("/notifications/count", methods=["GET"])
@login_required
def get_notification_count():
    """GET /notifications/count - Return the unread count."""
    count = db.get_unread_count(user_id=current_user.id)
    return jsonify({"unread_count": count})


@app.route("/notifications/mark_read", methods=["POST"])
@login_required
def mark_notifications_read():
    """POST /notifications/mark_read - Mark all notifications as read."""
    db.mark_all_read(user_id=current_user.id)
    return jsonify({"status": "ok"})


@app.route("/set_language/<lang>")
def set_language(lang: str):
    """
    GET /set_language/<lang>
    Saves the user's language choice in the session and redirects back.
    Supported: 'en', 'hi', 'kn'.

    The language takes effect on the next page load via get_locale(), which
    reads session['lang']. No need to touch g — the redirect is immediate.
    """
    supported = app.config.get('BABEL_SUPPORTED_LOCALES', ['en', 'hi', 'kn'])
    if lang in supported:
        session['lang'] = lang
        session.modified = True
    referrer = request.referrer or ''
    safe_back = referrer if referrer.startswith(request.host_url) else url_for('index')
    return redirect(safe_back)


@app.route("/dashboard_metrics", methods=["GET"])
@login_required
def dashboard_metrics():
    """
    GET /dashboard_metrics

    Returns aggregated data for radar chart rendering:
        - leadership_radar: data per leadership category (for Leadership Index chart)
        - employability_score: computed overall employability score
        - total_activities: number of activities logged
        - recent_activities: last 5 entries
    """
    user_id = authenticated_user_id()
    metrics = db.get_aggregated_metrics(user_id)
    recent = db.get_user_activities(user_id)[:5]

    all_categories = list(LEADERSHIP_CATEGORIES.keys())
    cat_lookup = {c["leadership_category"]: c["avg_magnitude"]
                  for c in metrics["category_breakdown"]}

    leadership_radar = {
        "labels": all_categories,
        "data": [round(cat_lookup.get(cat, 0), 2) for cat in all_categories]
    }

    employability_score = compute_employability_score(metrics)

    return jsonify({
        "status": "success",
        "leadership_radar": leadership_radar,
        "employability_score": metrics.get("avg_employability_score", employability_score),
        "total_activities": metrics["total_activities"],
        "overall_avg_magnitude": round(metrics["overall_avg_magnitude"], 2),
        "recent_activities": recent,
        "radar_averages": metrics.get("radar_averages", {}),
        "avg_leadership_index": metrics.get("avg_leadership_index", 0)
    }), 200


@app.route("/activities", methods=["GET"])
@login_required
def list_activities():
    """
    GET /activities
    Returns the authenticated user's logged activities.
    """
    user_id = authenticated_user_id()
    activities = db.get_user_activities(user_id)
    return jsonify({"status": "success", "activities": activities}), 200


@app.route("/history", methods=["GET"])
@login_required
def history():
    """
    GET /history
    Renders every saved activity for the authenticated user in a clean HTML table.
    """
    user_id = authenticated_user_id()
    activities = db.get_user_activities(user_id)

    # Compute summary stats for the header cards
    total = len(activities)
    avg_leadership    = round(sum(a.get("leadership_index", 0) or 0 for a in activities) / total, 1) if total else 0
    avg_employability = round(sum(a.get("employability_score", 0) or 0 for a in activities) / total, 1) if total else 0

    # Find the most common leadership_category as the 'top skill area'
    from collections import Counter
    cats = [a.get("leadership_category", "") for a in activities if a.get("leadership_category")]
    top_skill = Counter(cats).most_common(1)[0][0].split()[0] if cats else "—"

    return render_template(
        "history.html",
        activities=activities,
        avg_leadership=avg_leadership,
        avg_employability=avg_employability,
        top_skill=top_skill
    )


# ---------------------------------------------------------------------------
# PDF Portfolio Export
# ---------------------------------------------------------------------------

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

# Unicode ranges used to detect which script a piece of text is mostly written in,
# so the PDF can switch to a font that actually has glyphs for it. FPDF's built-in
# core fonts (Helvetica, etc.) only support Latin-1 and crash (FPDFUnicodeEncodingException)
# on Devanagari/Kannada text, which Gemini legitimately returns when the user's
# selected language is Hindi or Kannada.
_DEVANAGARI_RANGE = (0x0900, 0x097F)
_KANNADA_RANGE = (0x0C80, 0x0CFF)


def _detect_script(text: str) -> str:
    """Returns 'devanagari', 'kannada', or 'latin' based on the dominant script in text."""
    devanagari_count = sum(1 for ch in text if _DEVANAGARI_RANGE[0] <= ord(ch) <= _DEVANAGARI_RANGE[1])
    kannada_count = sum(1 for ch in text if _KANNADA_RANGE[0] <= ord(ch) <= _KANNADA_RANGE[1])
    if devanagari_count == 0 and kannada_count == 0:
        return "latin"
    return "devanagari" if devanagari_count >= kannada_count else "kannada"


def _register_unicode_fonts(pdf):
    """
    Registers the bundled Noto Sans font family (Latin / Devanagari / Kannada)
    on a fresh FPDF instance. Must be called once per FPDF() object — fpdf2
    binds fonts to the document instance, not globally.
    """
    pdf.add_font("NotoSans", "", os.path.join(FONTS_DIR, "NotoSans-Regular.ttf"))
    pdf.add_font("NotoSans", "B", os.path.join(FONTS_DIR, "NotoSans-Bold.ttf"))
    pdf.add_font("NotoSans", "I", os.path.join(FONTS_DIR, "NotoSans-Italic.ttf"))
    pdf.add_font("NotoSansDevanagari", "", os.path.join(FONTS_DIR, "NotoSansDevanagari-Regular.ttf"))
    pdf.add_font("NotoSansDevanagari", "B", os.path.join(FONTS_DIR, "NotoSansDevanagari-Bold.ttf"))
    pdf.add_font("NotoSansKannada", "", os.path.join(FONTS_DIR, "NotoSansKannada-Regular.ttf"))
    pdf.add_font("NotoSansKannada", "B", os.path.join(FONTS_DIR, "NotoSansKannada-Bold.ttf"))


_SCRIPT_FONT_FAMILY = {
    "latin": "NotoSans",
    "devanagari": "NotoSansDevanagari",
    "kannada": "NotoSansKannada",
}


def _set_script_aware_font(pdf, text: str, style: str, size: int):
    """
    Sets the active font to whichever registered family actually has glyphs
    for `text`'s dominant script. Devanagari/Kannada fonts only have Regular
    and Bold styles bundled (no italic) — Italic requests fall back to
    Regular for those scripts rather than raising.
    """
    family = _SCRIPT_FONT_FAMILY[_detect_script(text)]
    if family != "NotoSans" and style == "I":
        style = ""
    pdf.set_font(family, style, size)


class _BrochurePDF(FPDF):
    """FPDF subclass for the Professional Portfolio brochure. Overriding
    footer() (rather than drawing the footer inline) is required so fpdf2's
    auto-page-break guard (which is disabled only while self.in_footer is
    True) doesn't insert a spurious blank page — see _PortfolioPDF above for
    the same pattern used by the Career Intelligence Report."""
    footer_label = ""

    def footer(self):
        pdf_design.numbered_footer(self, self.footer_label)


def _pdf_tier_for(score_value):
    if score_value >= 75:
        return "Strong"
    if score_value >= 50:
        return "Developing"
    return "Needs Work"


def _dedupe_activities(activities):
    """Groups repeated identical log entries (same resume_snippet — the
    seed/demo data and quick re-submissions both produce these) into one,
    tracking how many times it was logged and the most recent timestamp,
    so the brochure doesn't show the same accomplishment N times."""
    groups = OrderedDict()
    for a in activities:
        key = a.get("resume_snippet") or a.get("mapped_skill") or ""
        if key not in groups:
            groups[key] = {**a, "_count": 1}
        else:
            groups[key]["_count"] += 1
            if (a.get("created_at") or "") > (groups[key].get("created_at") or ""):
                groups[key]["created_at"] = a["created_at"]
    return list(groups.values())


def _derive_strengths(score, unique_activities):
    """Turns the activities-derived score axes into plain-English strengths —
    no resume/ATS keyword matching involved, just what the logged activities
    themselves demonstrate."""
    strengths = []
    if score.leadership >= 60:
        strengths.append(f"Strong leadership signal across logged activities ({score.leadership:.0f}%)")
    if score.consistency >= 60:
        strengths.append(f"Consistent activity logging ({score.consistency:.0f}% consistency)")
    if score.communication >= 60:
        strengths.append(f"Clear, well-articulated activity descriptions ({score.communication:.0f}%)")
    if not strengths and unique_activities:
        strengths.append(f"{len(unique_activities)} real-world activities translated into career-relevant skills")
    return strengths[:3]


@app.route("/generate_pdf")
@login_required
@limiter.limit("10 per hour")
def generate_pdf():
    """
    GET /generate_pdf

    Generates the Professional Portfolio: a 9-page recruiter-facing brochure
    built entirely from the candidate's logged activities (Cover, About Me,
    Skills & Competencies, Featured Accomplishments, Achievements &
    Experience, Career Snapshot, Personal Growth, Recruiter one-pager,
    Contact/Closing) using the shared component library in
    services/pdf_design.py.

    Deliberately activities-only, not resume-based: this is the "invisible
    skill intelligence" document — it translates real-world logged activities
    into professional-equivalent skills and achievements, which is the whole
    point of ISIS. The resume-and-target-role gap analysis lives entirely in
    the separate Career Intelligence Report at /career/portfolio_pdf, which
    this route does not read from or duplicate.
    """
    validate_pdf_csrf_token()

    user_id = authenticated_user_id()
    user = db.get_user_by_id(user_id)
    candidate_name = (user["username"].strip().title() if user and user.get("username") else "Candidate")
    target_role = db.get_user_target_role(user_id) or "Not set"
    activities = db.get_user_activities(user_id)
    unique_activities = _dedupe_activities(activities)

    activity_skills = list({a.get("mapped_skill", "") for a in activities if a.get("mapped_skill")})

    # Skill-gap analysis (Role Match / recommendations) uses ONLY the skills
    # implied by logged activities — never resume skills — so this PDF stays
    # fully independent of whether a resume was ever uploaded. Isolated in
    # its own try/except: the embedding model can be flaky (slow/unreachable
    # huggingface.co), and a network hiccup here should only cost the Role
    # Match section, not the whole brochure.
    gap = None
    if activity_skills and target_role != "Not set":
        try:
            gap = skill_gap_engine.analyze_gap(target_role, activity_skills)
        except Exception:
            logger.warning("pdf_skill_gap_unavailable_falling_back", extra={"user_id": user_id})

    try:
        score = scoring_engine.compute(activities, gap.coverage_pct if gap else 0)
        plan = (learning_recommender.build_learning_plan(target_role, gap.missing, gap.partial, score)
                if gap else {"day_30": [], "day_60": [], "day_90": []})
        opps = opportunity_recommender.get_opportunities(target_role, gap.missing if gap else [])
    except Exception:
        logger.exception("pdf_data_fetch_failed", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("Could not load your portfolio data. Please try again.")}), 500

    d = pdf_design
    overall_tier = _pdf_tier_for(score.overall)
    tier_color = d.GREEN if overall_tier == "Strong" else (d.AMBER if overall_tier == "Developing" else d.RED)

    equivalency_counts = Counter(a.get("career_equivalency", "") for a in activities if a.get("career_equivalency"))
    top_equivalency = equivalency_counts.most_common(1)[0][0] if equivalency_counts else None
    tagline = top_equivalency or "Turning Real-World Experience Into Career Capital"

    avg_employability = sum(a.get("employability_score") or 0 for a in activities) / len(activities) if activities else 0
    avg_leadership = sum(a.get("leadership_index") or 0 for a in activities) / len(activities) if activities else 0
    peak_score = max((a.get("employability_score") or 0 for a in activities), default=0)
    skill_domains = len(activity_skills)

    # Skills grouped by career_equivalency -> mapped_skill, bar length = the
    # real average employability_score for that skill (an actual measured
    # value from the scoring engine, not a fabricated proficiency estimate).
    skill_groups = OrderedDict()
    for a in activities:
        cat = a.get("career_equivalency") or "General Experience"
        skill = a.get("mapped_skill") or ""
        if not skill:
            continue
        skill_groups.setdefault(cat, OrderedDict())
        entry = skill_groups[cat].setdefault(skill, {"count": 0, "score_sum": 0})
        entry["count"] += 1
        entry["score_sum"] += a.get("employability_score") or 0

    strengths = _derive_strengths(score, unique_activities)
    ranked = sorted(unique_activities, key=lambda a: a.get("employability_score") or 0, reverse=True)[:4]

    def go(pdf, label):
        pdf.footer_label = label
        d.new_page(pdf)

    try:
        pdf = _BrochurePDF()
        _register_unicode_fonts(pdf)
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.alias_nb_pages()
        today_str = datetime.date.today().strftime("%d %B %Y")

        # ── PAGE 1 — Cover ───────────────────────────────────────────────
        go(pdf, "Professional Portfolio")
        d.hero_band(pdf, d.PAGE_H, d.INDIGO, d.INDIGO_D)
        pdf.set_xy(0, 40)
        d.font(pdf, "B", 12); d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 6, "ISIS  \u2022  INVISIBLE SKILL INTELLIGENCE SYSTEM", align="C")
        pdf.set_xy(0, 90)
        d.font(pdf, "B", 30); d.set_text(pdf, d.WHITE)
        pdf.cell(d.PAGE_W, 14, candidate_name, align="C")
        pdf.set_xy(0, 106)
        d.font(pdf, "", 12); d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 6, tagline, align="C")
        pdf.set_xy(0, 114)
        d.font(pdf, "I", 10.5)
        pdf.cell(d.PAGE_W, 6, "Building Career Capital From Real-World Experience", align="C")

        if target_role != "Not set":
            d.card_bg(pdf, 55, 135, 100, 16, fill=(79, 82, 221), border=(79, 82, 221), radius=8)
            pdf.set_xy(55, 140)
            d.font(pdf, "B", 9.5); d.set_text(pdf, d.WHITE)
            pdf.cell(100, 6, f"Target Role: {target_role}", align="C")

        pdf.set_xy(0, 165)
        d.font(pdf, "B", 44); d.set_text(pdf, d.WHITE)
        pdf.cell(d.PAGE_W, 18, f"{score.overall:.0f}", align="C")
        pdf.set_xy(0, 186)
        d.font(pdf, "", 10); d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 6, f"CAREER READINESS  \u00b7  {overall_tier.upper()}", align="C")

        d.set_draw(pdf, (129, 140, 248)); pdf.set_line_width(0.3)
        pdf.line(55, 210, 155, 210)
        pdf.set_xy(30, 216)
        d.font(pdf, "", 9.5); d.set_text(pdf, (199, 210, 254))
        pdf.multi_cell(150, 5.2,
            f"{len(unique_activities)} real-world activities translated into demonstrated, career-relevant skills "
            f"\u2014 evidence of impact beyond a traditional resume.", align="C")
        pdf.set_xy(0, 255)
        d.font(pdf, "", 9)
        pdf.cell(d.PAGE_W, 5, f"Generated {today_str}", align="C")

        # ── PAGE 2 — About Me ────────────────────────────────────────────
        go(pdf, "About Me")
        d.section_title(pdf, "About Me", d.INDIGO, "Professional profile, strengths, and highlights")
        y = pdf.get_y()
        profile_text = f"{tagline}. {len(activities)} logged activities" + (
            f", targeting {target_role} roles with {gap.coverage_pct:.0f}% skill alignment already in place." if gap
            else ", demonstrating consistent real-world impact.")
        d.profile_card(pdf, d.MARGIN, y, d.CONTENT_W, 26, "Professional Profile", [profile_text], d.INDIGO)
        pdf.set_y(y + 30)
        y = pdf.get_y()
        objective = (f"To build a career as a {target_role}, applying real-world experience and demonstrated "
                     f"skills to measurable professional impact." if target_role != "Not set" else
                     "To translate real-world experience into recognized, measurable professional skills.")
        d.profile_card(pdf, d.MARGIN, y, d.CONTENT_W, 18, "Career Objective", [objective], d.PINK)
        pdf.set_y(y + 22)

        d.font(pdf, "B", 10.5); d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 6, "Top Strengths", ln=True)
        pdf.ln(1)
        col_w = (d.CONTENT_W - 4) / 2
        y = pdf.get_y()
        show_strengths = strengths or ["Building a strong foundation across logged activities"]
        for i, s in enumerate(show_strengths[:4]):
            col, row = i % 2, i // 2
            x = d.MARGIN + col * (col_w + 4)
            d.profile_card(pdf, x, y + row * 20, col_w, 17, f"Strength {i+1}", [s], d.GREEN)
        rows = math.ceil(min(len(show_strengths), 4) / 2)
        pdf.set_y(y + rows * 20 + 4)

        d.font(pdf, "B", 10.5); d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 6, "Core Competencies", ln=True)
        pdf.ln(1)
        x, cy = d.MARGIN, pdf.get_y()
        for skill in activity_skills[:8]:
            d.font(pdf, "B", 7.5)
            cw = d.text_w(pdf, skill) + 6
            if x + cw > d.PAGE_W - d.MARGIN:
                x = d.MARGIN
                cy += 8
            d.pill_chip(pdf, x, cy, skill, d.INDIGO, filled=False)
            x += cw + 3
        pdf.set_y(cy + 12)

        d.font(pdf, "B", 10.5); d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 6, "Professional Highlights", ln=True)
        pdf.ln(1)
        d.kpi_grid(pdf, [
            {"label": "Activities Logged", "value_str": str(len(activities)), "color": d.INDIGO},
            {"label": "Skill Domains Active", "value_str": str(skill_domains), "color": d.GREEN},
            {"label": "Peak Employability Score", "value_str": f"{peak_score:.0f}", "color": d.AMBER},
        ], cols=3, card_h=24)

        # ── PAGE 3 — Skills & Competencies ────────────────────────────────
        go(pdf, "Skills & Competencies")
        d.section_title(pdf, "Skills & Competencies", d.INDIGO,
                         "Grouped by professional equivalency, sized by demonstrated employability score")
        palette = [d.INDIGO, d.GREEN, d.AMBER, d.PINK, d.BLUE, d.RED, (14, 165, 233), (168, 85, 247)]
        if not skill_groups:
            d.font(pdf, "I", 10); d.set_text(pdf, d.MUTED)
            pdf.multi_cell(d.CONTENT_W, 6, "Log activities to populate your skills matrix.")
        for i, (cat, skills) in enumerate(skill_groups.items()):
            color = palette[i % len(palette)]
            rows_pct = [(skill, info["score_sum"] / info["count"]) for skill, info in skills.items()]
            d.skill_bar_group(pdf, cat, rows_pct, color)

        # ── PAGE 4 — Featured Accomplishments ──────────────────────────────
        go(pdf, "Featured Accomplishments")
        d.section_title(pdf, "Featured Accomplishments", d.PINK,
                         "Real-world activities, translated into professional achievements")
        proj_colors = [d.INDIGO, d.GREEN, d.AMBER, d.PINK]
        proj_cards = []
        for i, a in enumerate(ranked):
            tags = [t for t in [a.get("career_equivalency"),
                                 a.get("market_value") and f"{a['market_value']} Value"] if t]
            proj_cards.append({
                "title": a.get("mapped_skill", "Activity"),
                "description": a.get("resume_snippet", ""),
                "tech": tags,
                "color": proj_colors[i % len(proj_colors)],
            })
        if proj_cards:
            d.project_grid(pdf, proj_cards, cols=1, card_h=40)
        else:
            d.font(pdf, "I", 10); d.set_text(pdf, d.MUTED)
            pdf.multi_cell(d.CONTENT_W, 6, "Log your first activity to feature it here.")

        # ── PAGE 5 — Achievements & Experience ──────────────────────────────
        go(pdf, "Achievements & Experience")
        d.section_title(pdf, "Achievements & Experience", d.GREEN, "A timeline of your logged real-world activities")
        timeline_items = sorted(unique_activities, key=lambda a: a.get("created_at") or "", reverse=True)[:10]
        if timeline_items:
            for i, a in enumerate(timeline_items):
                date_str = (a.get("created_at") or "")[:10]
                tag = f"\u00d7{a['_count']}" if a.get("_count", 1) > 1 else (a.get("market_value") or "Logged")
                d.achievement_item(pdf, date_str, a.get("mapped_skill", "Activity"), tag, d.GREEN,
                                   subtitle=a.get("career_equivalency"), is_last=(i == len(timeline_items) - 1))
        else:
            d.font(pdf, "I", 10); d.set_text(pdf, d.MUTED)
            pdf.multi_cell(d.CONTENT_W, 6, "No activities logged yet.")

        # ── PAGE 6 — Career Snapshot ───────────────────────────────────────
        go(pdf, "Career Snapshot")
        d.section_title(pdf, "Career Snapshot", d.INDIGO, "Where you stand right now, at a glance")
        d.kpi_grid(pdf, [
            {"label": "Career Readiness", "value_str": f"{score.overall:.0f}%", "color": d.INDIGO, "sub": overall_tier},
            {"label": "Role Match", "value_str": (f"{gap.coverage_pct:.0f}%" if gap else "\u2014"),
             "color": d.tier_color(gap.coverage_pct) if gap else d.FAINT},
            {"label": "Avg Employability", "value_str": f"{avg_employability:.0f}%", "color": d.tier_color(avg_employability)},
            {"label": "Avg Leadership Index", "value_str": f"{avg_leadership:.0f}%", "color": d.tier_color(avg_leadership)},
        ], cols=2, card_h=28)
        pdf.ln(8)
        d.font(pdf, "B", 10.5); d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 6, "Top Skills", ln=True)
        pdf.ln(1)
        x, y = d.MARGIN, pdf.get_y()
        for sk in activity_skills[:6] or ["Log activities to populate"]:
            w = d.badge(pdf, x, y, sk, d.INDIGO) + 3
            if x + w > d.PAGE_W - d.MARGIN:
                x = d.MARGIN; y += 8
            else:
                x += w
        pdf.set_xy(d.MARGIN, y + 12)
        d.font(pdf, "B", 10.5); d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 6, "Top Recommendations", ln=True)
        pdf.ln(1)
        rec_titles = []
        for key in ("projects", "certifications", "hackathons"):
            for item in opps.get(key, [])[:1]:
                rec_titles.append(item.get("title", ""))
        if rec_titles:
            for t in rec_titles[:3]:
                d.font(pdf, "", 9); d.set_text(pdf, d.INK)
                pdf.cell(d.CONTENT_W, 6, f"\u2022 {t}", ln=True)
        else:
            d.font(pdf, "I", 9.5); d.set_text(pdf, d.MUTED)
            pdf.cell(d.CONTENT_W, 6, "Set a target role to see personalised recommendations.", ln=True)

        # ── PAGE 7 — Personal Growth ────────────────────────────────────────
        go(pdf, "Personal Growth")
        d.section_title(pdf, "Personal Growth", d.AMBER, "Your roadmap for the next 90 days")

        def _first_item_text(items):
            return items[0].get("skill", "") if items else "Log more activities to unlock this phase"

        d.mini_roadmap(pdf, [
            ("30 Days", "Foundation", d.INDIGO, _first_item_text(plan["day_30"])),
            ("60 Days", "Development", d.GREEN, _first_item_text(plan["day_60"])),
            ("90 Days", "Mastery", d.AMBER, _first_item_text(plan["day_90"])),
        ])
        pdf.ln(6)
        d.font(pdf, "B", 10.5); d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 6, "Next Certifications", ln=True)
        pdf.ln(1)
        certs = opps.get("certifications", [])[:2]
        if certs:
            cards = [{"title": c.get("title", ""),
                      "meta": [f"Provider: {c.get('provider','')}", f"Cost: {c.get('cost','')}"],
                      "color": d.GREEN, "tag": "Certification"} for c in certs]
            d.recommendation_grid(pdf, cards, cols=2, card_h=26)
        else:
            d.font(pdf, "I", 9.5); d.set_text(pdf, d.MUTED)
            pdf.cell(d.CONTENT_W, 6, "Set a target role to see certification suggestions.", ln=True)

        # ── PAGE 8 — Recruiter Page ────────────────────────────────────────
        go(pdf, "Recruiter Page")
        d.section_title(pdf, "For Recruiters \u2014 One-Page Summary", d.INDIGO,
                         f"{candidate_name}" + (f"  \u00b7  {target_role}" if target_role != "Not set" else ""))
        y = pdf.get_y()
        d.card_bg(pdf, d.MARGIN, y, d.CONTENT_W, 20, fill=d.SURFACE)
        pdf.set_xy(d.MARGIN + 5, y + 4)
        d.font(pdf, "B", 11); d.set_text(pdf, d.INK)
        pdf.cell(80, 6, f"Overall: {overall_tier}", ln=False)
        d.badge(pdf, d.PAGE_W - d.MARGIN - 30, y + 5, f"{score.overall:.0f}/100", tier_color)
        pdf.set_xy(d.MARGIN + 5, y + 12)
        d.font(pdf, "", 8.5); d.set_text(pdf, d.MUTED)
        pdf.multi_cell(d.CONTENT_W - 10, 4.4,
            f"{candidate_name.split()[0]} shows {overall_tier.lower()} readiness"
            + (f" for {target_role} roles with {gap.coverage_pct:.0f}% skill alignment." if gap
               else f", backed by {len(unique_activities)} demonstrated real-world activities."))
        pdf.set_y(y + 24)

        col_w = (d.CONTENT_W - 6) / 2
        sy = pdf.get_y()
        d.font(pdf, "B", 9.5); d.set_text(pdf, d.GREEN)
        pdf.set_xy(d.MARGIN, sy); pdf.cell(col_w, 5.5, "Why Hire Me", ln=True)
        d.font(pdf, "", 8); d.set_text(pdf, d.INK)
        for s in (strengths or ["Real-world experience, professionally translated"])[:3]:
            pdf.set_x(d.MARGIN)
            pdf.multi_cell(col_w, 4.2, "\u2022 " + s)
        left_end = pdf.get_y()

        d.font(pdf, "B", 9.5); d.set_text(pdf, d.INDIGO)
        pdf.set_xy(d.MARGIN + col_w + 6, sy); pdf.cell(col_w, 5.5, "Strongest Competencies", ln=True)
        x2, y2 = d.MARGIN + col_w + 6, pdf.get_y()
        for sk in activity_skills[:5] or ["Log activities to populate"]:
            w = d.badge(pdf, x2, y2, sk, d.INDIGO) + 3
            if x2 + w > d.PAGE_W - d.MARGIN:
                x2 = d.MARGIN + col_w + 6; y2 += 7
            else:
                x2 += w
        right_end = y2 + 7
        pdf.set_y(max(left_end, right_end) + 3)

        d.divider(pdf, gap_before=1, gap_after=2)
        d.kpi_grid(pdf, [
            {"label": "Consistency", "value_str": f"{score.consistency:.0f}%", "color": d.tier_color(score.consistency)},
            {"label": "Career Potential", "value_str": f"{score.growth:.0f}%", "color": d.tier_color(score.growth)},
        ], cols=2, card_h=22)
        pdf.ln(6)
        d.font(pdf, "B", 9.5); d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 5.5, "Key Accomplishments", ln=True)
        d.font(pdf, "", 8.3); d.set_text(pdf, d.MUTED)
        for a in ranked[:3]:
            pdf.cell(d.CONTENT_W, 4.6, f"\u2022 {d.truncate(pdf, a.get('mapped_skill',''), d.CONTENT_W - 5)}", ln=True)
        pdf.ln(2)
        d.card_bg(pdf, d.MARGIN, pdf.get_y(), d.CONTENT_W, 14, fill=d.SURFACE)
        pdf.set_xy(d.MARGIN + 5, pdf.get_y() + 3)
        d.font(pdf, "B", 8.7); d.set_text(pdf, d.INK)
        pdf.cell(35, 6, "Recommendation:", ln=False)
        d.font(pdf, "", 8.7); d.set_text(pdf, d.MUTED)
        next_action = (f"Log more activities in areas relevant to {target_role} to strengthen role alignment."
                       if target_role != "Not set" else "Set a target role in the Career Hub to unlock tailored guidance.")
        pdf.multi_cell(d.CONTENT_W - 40, 4.4, next_action)

        # ── PAGE 9 — Contact / Closing ──────────────────────────────────────
        go(pdf, "Contact")
        d.hero_band(pdf, d.PAGE_H, d.INDIGO, d.INDIGO_D)
        pdf.set_xy(0, 60)
        d.font(pdf, "B", 20); d.set_text(pdf, d.WHITE)
        pdf.cell(d.PAGE_W, 10, "Thank You", align="C")
        pdf.set_xy(0, 74)
        d.font(pdf, "", 10); d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 6, f"for reviewing {candidate_name.split()[0]}'s Professional Portfolio", align="C")

        cy = 110
        for lbl in ("GitHub", "LinkedIn", "Email", "Portfolio Website"):
            d.card_bg(pdf, 55, cy, 100, 12, fill=(79, 82, 221), border=(79, 82, 221), radius=6)
            pdf.set_xy(55, cy + 3)
            d.font(pdf, "B", 8.5); d.set_text(pdf, (199, 210, 254))
            pdf.cell(40, 6, lbl, align="L")
            pdf.set_xy(115, cy + 3)
            d.font(pdf, "I", 8.5)
            pdf.cell(35, 6, "Add in profile", align="R")
            cy += 15

        pdf.set_xy(0, cy + 8)
        d.set_draw(pdf, (129, 140, 248)); pdf.set_line_width(0.3)
        pdf.line(70, cy + 8, 140, cy + 8)
        pdf.set_xy(0, cy + 14)
        d.font(pdf, "", 9); d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 5, "Generated by ISIS \u2014 AI Career Intelligence Platform", align="C")
        pdf.set_xy(0, cy + 20)
        pdf.cell(d.PAGE_W, 5, today_str, align="C")

        buf = io.BytesIO()
        pdf.output(buf)
        buf.seek(0)
    except Exception:
        logger.exception("pdf_rendering_failed", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("Could not generate your PDF. Please try again.")}), 500

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="ISIS_Professional_Portfolio.pdf"
    )



# ---------------------------------------------------------------------------
# Phase 4 — Career Intelligence Platform Routes
# ---------------------------------------------------------------------------

@app.route("/career")
@login_required
def career_page():
    """Career Intelligence Hub page."""
    user_id = authenticated_user_id()
    target_role = db.get_user_target_role(user_id)
    roles = role_taxonomy.list_target_roles()
    resume = db.get_latest_resume(user_id)
    return render_template(
        "career.html",
        target_role=target_role,
        roles=roles,
        has_resume=resume is not None,
        resume_filename=resume["filename"] if resume else None,
    )


@app.route("/career/set_target", methods=["POST"])
@login_required
def set_target_role():
    """Saves the user's chosen target career role."""
    user_id = authenticated_user_id()
    role = request.form.get("target_role", "").strip()
    if role not in role_taxonomy.list_target_roles():
        flash(_("Please choose one of the roles from the list."), "error")
        return redirect(url_for("career_page"))
    user_repository.set_target_role(user_id, role)
    flash(_("Got it! You're now aiming for %(role)s.", role=role), "success")
    return redirect(url_for("career_page"))


@app.route("/career/upload_resume", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def upload_resume():
    """
    Accepts a PDF or DOCX resume, parses it, and stores the result in the DB.
    Returns JSON so the frontend can update the UI without a full page reload.
    """
    user_id = authenticated_user_id()

    if "resume" not in request.files:
        return jsonify({"status": "error", "message": _("Please choose a file to upload.")}), 400

    file = request.files["resume"]
    if not file.filename:
        return jsonify({"status": "error", "message": _("Please choose a file first.")}), 400

    filename = secure_filename(file.filename)
    file_bytes = file.read()

    try:
        parsed = resume_parser.parse_resume(filename, file_bytes)
    except resume_parser.ResumeParseError as e:
        return jsonify({"status": "error", "message": str(e)}), 422
    except Exception:
        logger.exception("resume_upload_unexpected_error", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("We had trouble reading that file. Please try again, or try a different file.")}), 500

    try:
        db.save_resume(user_id, filename, parsed)
    except Exception:
        logger.exception("resume_save_failed", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("We read your resume but couldn't save it just now. Please try again.")}), 500

    return jsonify({
        "status": "success",
        "message": _("Great! We've added '%(filename)s' to your profile.", filename=filename),
        "candidate_skills": parsed["candidate_skills"],
        "sections_found": [k for k, v in parsed["sections"].items() if v.strip()],
    }), 200


@app.route("/career/analysis")
@login_required
def career_analysis():
    """
    Main Phase 4 intelligence endpoint.
    Returns the full career readiness analysis as JSON:
      - skill gap (resume + activity skills vs target role)
      - career readiness score (6 axes)
      - 30/60/90 day learning plan
      - opportunity recommendations
      - growth chart data
    """
    user_id = authenticated_user_id()

    target_role = db.get_user_target_role(user_id)
    if not target_role:
        return jsonify({
            "status": "no_target",
            "message": _("Please tell us what role you're hoping for first, in the Career Hub."),
        }), 200

    activities = db.get_user_activities(user_id)
    resume = db.get_latest_resume(user_id)

    # Build the user skills list from BOTH sources.
    # Entries with a zero confidence score are EXCLUDED: when the NLP
    # matcher finds no genuinely confident match, mapped_skill is still
    # persisted as a display-only placeholder (see
    # nlp/skill_matcher._no_confident_match_result and the local-fallback
    # branch of /analyze_activity). That placeholder is fine to show on the
    # dashboard/history/PDF as a label for what was logged, but it must not
    # be treated as a real detected skill here — doing so would contradict
    # the NLP stage, which explicitly found nothing confident.
    activity_skills = list({
        a.get("mapped_skill", "") for a in activities
        if a.get("mapped_skill", "").strip()
        and float(a.get("nlp_confidence_pct") or 0) > 0
    })
    # Also include the NLP-engine-matched primary skill phrases.
    # Entries with a zero confidence score are EXCLUDED: when the NLP
    # matcher finds no genuinely confident match it returns a clearly
    # labelled placeholder skill with confidence_pct == 0.0 (see
    # nlp/skill_matcher._no_confident_match_result), which is stored as-is
    # for display. Feeding that placeholder into the skill-gap engine would
    # contradict the matcher one stage earlier — the user would be told "no
    # skill detected" by the NLP stage and then have that same non-detection
    # counted as a detected skill in user_skill_count/coverage.
    activity_skill_phrases = list({
        a.get("nlp_primary_skill", "") for a in activities
        if a.get("nlp_primary_skill", "").strip()
        and float(a.get("nlp_confidence_pct") or 0) > 0
    })

    resume_skills = resume["candidate_skills"] if resume else []

    all_user_skills = list(dict.fromkeys(
        activity_skills + activity_skill_phrases + resume_skills
    ))  # deduplicated, order preserved

    # 1. Skill gap analysis
    try:
        gap = skill_gap_engine.analyze_gap(target_role, all_user_skills)
    except Exception:
        logger.exception("skill_gap_analysis_failed", extra={"user_id": user_id})
        return jsonify({
            "status": "error",
            "message": _(
                "Skill gap analysis failed. This usually means the local AI model "
                "couldn't be loaded (it needs to download once from the internet the "
                "first time it's used). Check your connection and try again in a moment."
            ),
        }), 500

    # 2. Career readiness score
    score = scoring_engine.compute(activities, gap.coverage_pct)

    # 3. Learning plan
    plan = learning_recommender.build_learning_plan(
        target_role, gap.missing, gap.partial, score
    )

    # 4. Opportunities
    opps = opportunity_recommender.get_opportunities(target_role, gap.missing)

    # 5. Growth tracker data
    growth = growth_tracker.compute_growth_data(activities)

    # 6. ATS + recruiter metrics (Phase 4.5B)
    resume_text = resume["raw_text"] if resume else ""
    ats_data = ats_engine.compute_ats(target_role, all_user_skills, resume_text, activities)
    recruiter = ats_engine.compute_recruiter_summary(target_role, score, ats_data, activities, resume_text)

    # Serialize axis_details (dataclass → dict) for JSON
    def _serialize_axis(detail):
        return {
            "summary":               detail.summary,
            "contributing_factors":  detail.contributing_factors,
            "matched_evidence":      detail.matched_evidence,
            "missing_evidence":      detail.missing_evidence,
            "confidence":            detail.confidence,
        }

    return jsonify({
        "status": "ok",
        "target_role": target_role,
        "gap": {
            "matched": gap.matched,
            "partial": gap.partial,
            "missing": gap.missing,
            "coverage_pct": gap.coverage_pct,
            "core_coverage_pct": gap.core_coverage_pct,
            "user_skill_count": gap.user_skill_count,
        },
        "score": {
            "overall":       score.overall,
            "technical":     score.technical,
            "leadership":    score.leadership,
            "communication": score.communication,
            "consistency":   score.consistency,
            "growth":        score.growth,
            "explanations":  score.explanations,
            "axis_details":  {k: _serialize_axis(v) for k, v in score.axis_details.items()},
        },
        "ats":       ats_data,
        "recruiter": recruiter,
        "learning_plan": plan,
        "opportunities": opps,
        "growth": growth,
        "resume_uploaded": resume is not None,
    })


class _PortfolioPDF(FPDF):
    """
    FPDF subclass used only by career_portfolio_pdf(). Overriding footer()
    is the fpdf2-idiomatic way to draw a page footer: fpdf2 only disables its
    auto-page-break guard while self.in_footer is True, so drawing the footer
    from here (rather than calling pdf_design.page_footer directly at the end
    of each page's content) avoids a spurious extra blank page per section.
    """
    footer_label = ""

    def footer(self):
        pdf_design.page_footer(self, self.footer_label)


@app.route("/career/portfolio_pdf")
@login_required
def career_portfolio_pdf():
    """
    Generates a 10-page Career Intelligence Portfolio PDF using the
    component-based design system in services/pdf_design.py:
      P1  — Executive Cover (candidate, target role, readiness gauge)
      P2  — Executive Dashboard (KPI cards) + Recruiter Snapshot checklist
      P3  — Skill Matrix (Strong / Intermediate / Needs Improvement + gaps)
      P4  — Career Intelligence (5-axis score cards with evidence + confidence)
      P5  — Charts (readiness radar, activity-mix donut, weekly bars, growth trend)
      P6  — 30/60/90 Day Learning Roadmap (timeline)
      P7  — Recommendations (projects / hackathons / certifications / OSS cards)
      P8  — ATS Report (score cards, missing keywords, improvement suggestions)
      P9  — Recruiter Summary (verdict, strengths, improvement areas, top skills)
      P10 — Closing page

    All data comes from the same engines the dashboard already uses
    (skill_gap_engine, scoring_engine, ats_engine, learning_recommender,
    opportunity_recommender, growth_tracker) — this route only changes how
    that data is laid out on the page, not what is computed.
    """
    user_id     = authenticated_user_id()
    user        = db.get_user_by_id(user_id)
    candidate_name = (user["username"].strip().title() if user and user.get("username") else "Candidate")
    target_role = db.get_user_target_role(user_id) or "Not set"
    activities  = db.get_user_activities(user_id)
    resume      = db.get_latest_resume(user_id)

    activity_skills = list({a.get("mapped_skill", "") for a in activities if a.get("mapped_skill")})
    resume_skills   = resume["candidate_skills"] if resume else []
    all_skills      = list(dict.fromkeys(activity_skills + resume_skills))
    resume_text     = resume["raw_text"] if resume else ""

    try:
        gap       = skill_gap_engine.analyze_gap(target_role, all_skills) if all_skills else None
        score     = scoring_engine.compute(activities, gap.coverage_pct if gap else 0)
        ats       = ats_engine.compute_ats(target_role, all_skills, resume_text, activities)
        recruiter = ats_engine.compute_recruiter_summary(target_role, score, ats, activities, resume_text)
        plan      = (learning_recommender.build_learning_plan(target_role, gap.missing, gap.partial, score)
                     if gap else {"day_30": [], "day_60": [], "day_90": []})
        opps      = opportunity_recommender.get_opportunities(target_role, gap.missing if gap else [])
        growth    = growth_tracker.compute_growth_data(activities)
    except Exception:
        logger.exception("career_pdf_analysis_failed", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("We couldn't put your portfolio together just now. Please try again.")}), 500

    d = pdf_design

    def go(pdf, label):
        pdf.footer_label = label
        d.new_page(pdf)

    try:
        pdf = _PortfolioPDF()
        _register_unicode_fonts(pdf)
        pdf.set_auto_page_break(auto=True, margin=20)
        today_str = datetime.date.today().strftime("%d %B %Y")

        # ── PAGE 1 — Executive Cover ─────────────────────────────────────
        go(pdf, "Cover")
        d.set_fill(pdf, d.INDIGO)
        pdf.rect(0, 0, d.PAGE_W, d.PAGE_H, "F")
        d.set_fill(pdf, d.INDIGO_D)
        with pdf.local_context(fill_opacity=0.5):
            pdf.ellipse(-40, -50, 160, 160, style="F")
            pdf.ellipse(140, 220, 160, 160, style="F")

        pdf.set_xy(0, 42)
        d.font(pdf, "B", 12)
        d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 6, "ISIS  \u2022  INVISIBLE SKILL INTELLIGENCE SYSTEM", align="C")
        pdf.set_xy(0, 54)
        d.font(pdf, "B", 27)
        d.set_text(pdf, d.WHITE)
        pdf.cell(d.PAGE_W, 14, "Career Intelligence Portfolio", align="C")
        pdf.set_xy(0, 70)
        d.font(pdf, "", 11)
        d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 6, "AI-Powered Professional Skills Assessment Report", align="C")

        d.card_bg(pdf, 55, 95, 100, 30, fill=(79, 82, 221), border=(79, 82, 221), radius=4)
        pdf.set_xy(55, 101)
        d.font(pdf, "", 8.5)
        d.set_text(pdf, (199, 210, 254))
        pdf.cell(100, 5, "CANDIDATE", align="C")
        pdf.set_xy(55, 107)
        d.font(pdf, "B", 13)
        d.set_text(pdf, d.WHITE)
        pdf.cell(100, 7, candidate_name, align="C")
        pdf.set_xy(55, 116)
        d.font(pdf, "", 9)
        d.set_text(pdf, (199, 210, 254))
        pdf.cell(100, 5, f"Target Role: {target_role}", align="C")

        d.circular_gauge(pdf, 105, 178, 62, score.overall, d.WHITE, "Career Readiness / 100", value_size=32)

        axes_row = [("Technical", score.technical), ("Leadership", score.leadership),
                    ("Communication", score.communication), ("Consistency", score.consistency),
                    ("Growth", score.growth)]
        row_y = 222
        seg_w = d.CONTENT_W / len(axes_row)
        for i, (lbl, val) in enumerate(axes_row):
            x = d.MARGIN + i * seg_w
            d.font(pdf, "B", 13)
            d.set_text(pdf, d.WHITE)
            pdf.set_xy(x, row_y)
            pdf.cell(seg_w, 6, f"{val:.0f}", align="C")
            d.font(pdf, "", 7.5)
            d.set_text(pdf, (199, 210, 254))
            pdf.set_xy(x, row_y + 6)
            pdf.cell(seg_w, 5, lbl, align="C")

        d.set_draw(pdf, (129, 140, 248))
        pdf.set_line_width(0.3)
        pdf.line(30, 245, 180, 245)
        pdf.set_xy(0, 250)
        d.font(pdf, "", 9)
        d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 5, f"Generated {today_str}  |  Confidential Candidate Report", align="C")

        # ── PAGE 2 — Executive Dashboard + Recruiter Snapshot ───────────
        go(pdf, "Page 2 \u00b7 Executive Dashboard")
        d.section_title(pdf, "Executive Dashboard", d.INDIGO,
                         "Six headline metrics summarising overall candidacy strength")
        kpis = [
            {"label": "Career Readiness", "value_str": f"{score.overall:.0f}%", "color": d.INDIGO,
             "sub": recruiter["overall_tier"]},
            {"label": "ATS Score", "value_str": f"{ats['ats_score']:.0f}%",
             "color": d.tier_color(ats['ats_score']), "sub": "Keyword coverage"},
            {"label": "Resume Strength", "value_str": f"{ats['resume_strength']:.0f}%",
             "color": d.tier_color(ats['resume_strength']), "sub": "Bullet quality"},
            {"label": "Interview Readiness", "value_str": f"{ats['interview_ready']:.0f}%",
             "color": d.tier_color(ats['interview_ready']), "sub": "Composite signal"},
            {"label": "Role Coverage", "value_str": f"{gap.coverage_pct:.0f}%" if gap else "0%",
             "color": d.tier_color(gap.coverage_pct if gap else 0),
             "sub": f"{len(gap.matched) if gap else 0} skills matched"},
            {"label": "Portfolio Completeness", "value_str": f"{ats['completeness']:.0f}%",
             "color": d.tier_color(ats['completeness']), "sub": "Profile setup"},
        ]
        d.kpi_grid(pdf, kpis, cols=3, card_h=30)
        pdf.ln(8)
        d.section_title(pdf, "Recruiter Snapshot", d.GREEN, "What a hiring manager sees at a glance")
        checklist = ats.get("checklist", {})
        chk_labels = {"target_role_set": "Target role configured", "resume_uploaded": "Resume uploaded",
                      "activities_logged": "3+ activities logged", "bullets_generated": "Resume bullets generated",
                      "skills_extracted": "Skills extracted", "quantified_bullets": "Measurable achievements present"}
        col_w = d.CONTENT_W / 2
        start_y = pdf.get_y()
        for i, (k, lbl) in enumerate(chk_labels.items()):
            col, row = i % 2, i // 2
            d.checklist_row(pdf, d.MARGIN + col * col_w, start_y + row * 7, col_w, lbl, checklist.get(k, False))

        # ── PAGE 3 — Skill Matrix ────────────────────────────────────────
        go(pdf, "Page 3 \u00b7 Skill Matrix")
        d.section_title(pdf, f"Skill Matrix \u2014 {target_role}", d.INDIGO,
                         "Matched strengths vs. skills to develop, grouped by proficiency tier")
        matched_list = gap.matched if gap else []
        partial_list = gap.partial if gap else []
        missing_list = gap.missing if gap else []

        def _bucket(m):
            s = m["similarity"] * 100
            if s >= 80:
                return "Strong"
            if s >= 55:
                return "Intermediate"
            return "Needs Improvement"

        groups = {"Strong": [], "Intermediate": [], "Needs Improvement": []}
        for m in matched_list + partial_list:
            groups[_bucket(m)].append(m)
        group_colors = {"Strong": d.GREEN, "Intermediate": d.AMBER, "Needs Improvement": d.RED}
        if not any(groups.values()):
            d.font(pdf, "I", 10)
            d.set_text(pdf, d.MUTED)
            pdf.multi_cell(d.CONTENT_W, 6, "No matched skills yet — upload a resume and log activities to populate this matrix.")
            pdf.ln(2)
        for gname, members in groups.items():
            if not members:
                continue
            color = group_colors[gname]
            hy = pdf.get_y()
            d.set_fill(pdf, color)
            pdf.ellipse(d.MARGIN + 0.8, hy + 1.6, 3.2, 3.2, style="F")
            pdf.set_xy(d.MARGIN + 6, hy)
            d.font(pdf, "B", 10)
            d.set_text(pdf, color)
            pdf.cell(d.CONTENT_W - 6, 6, f"{gname}  ({len(members)})", ln=True)
            pdf.ln(1)
            for m in members:
                d.metric_row(pdf, m["skill"], m["similarity"] * 100, color,
                             sub_label=f'via: {m.get("matched_by","")[:70]}')
            pdf.ln(2)
        d.divider(pdf)
        d.font(pdf, "B", 10.5)
        d.set_text(pdf, d.RED)
        pdf.cell(d.CONTENT_W, 6, f"Skills to Develop  ({len(missing_list)} gaps)", ln=True)
        pdf.ln(1)
        if not missing_list:
            d.font(pdf, "I", 9.5)
            d.set_text(pdf, d.MUTED)
            pdf.cell(d.CONTENT_W, 6, "No gaps identified yet.", ln=True)
        for m in missing_list:
            tag_color = d.RED if m["tier"] == "core" else d.AMBER
            y = pdf.get_y()
            d.font(pdf, "", 9.5)
            d.set_text(pdf, d.INK)
            pdf.cell(d.CONTENT_W - 26, 6, m["skill"], ln=False)
            d.badge(pdf, d.PAGE_W - d.MARGIN - 24, y + 0.3, m["tier"], tag_color)
            pdf.ln(6.5)
        if ats.get("missing_keywords"):
            d.divider(pdf)
            d.font(pdf, "B", 10)
            d.set_text(pdf, d.AMBER)
            pdf.cell(d.CONTENT_W, 6, "Missing ATS Keywords", ln=True)
            pdf.ln(1)
            x, y = d.MARGIN, pdf.get_y()
            for kw in ats["missing_keywords"][:14]:
                w = d.badge(pdf, x, y, kw, d.AMBER, filled=False) + 3
                if x + w > d.PAGE_W - d.MARGIN:
                    x = d.MARGIN
                    y += 8
                else:
                    x += w

        # ── PAGE 4 — Career Intelligence (axis score cards) ─────────────
        go(pdf, "Page 4 \u00b7 Career Intelligence")
        d.section_title(pdf, "Career Intelligence", d.PINK,
                         "Five-axis readiness breakdown with evidence and model confidence")
        axis_meta = [
            ("technical", "Technical", d.INDIGO), ("leadership", "Leadership", d.GREEN),
            ("communication", "Communication", d.AMBER), ("consistency", "Consistency", d.BLUE),
            ("growth", "Growth", d.PINK),
        ]
        for key, label, color in axis_meta:
            detail = score.axis_details.get(key)
            val = getattr(score, key)
            y = pdf.get_y()
            card_h = 24
            d.card_bg(pdf, d.MARGIN, y, d.CONTENT_W, card_h)
            d.set_fill(pdf, color)
            pdf.rect(d.MARGIN, y, 2.2, card_h, "F", round_corners=True, corner_radius=1)
            pdf.set_xy(d.MARGIN + 6, y + 3)
            d.font(pdf, "B", 11)
            d.set_text(pdf, d.INK)
            pdf.cell(40, 6, label, ln=False)
            d.font(pdf, "B", 14)
            d.set_text(pdf, color)
            pdf.cell(20, 6, f"{val:.0f}%", ln=False)
            if detail:
                conf_x = pdf.get_x()
                d.font(pdf, "", 7.5)
                d.set_text(pdf, d.FAINT)
                pdf.cell(d.CONTENT_W - (conf_x - d.MARGIN) - 4, 6, f"Confidence: {detail.confidence:.0f}%", align="R")
            pdf.set_xy(d.MARGIN + 6, y + 10)
            d.font(pdf, "", 8.3)
            d.set_text(pdf, d.MUTED)
            summary = detail.summary if detail else score.explanations.get(key, "")
            pdf.multi_cell(d.CONTENT_W - 10, 4.2, d.truncate(pdf, summary, (d.CONTENT_W - 10) * 3))
            if detail and detail.matched_evidence:
                pdf.set_xy(d.MARGIN + 6, y + 18)
                d.font(pdf, "I", 7.5)
                d.set_text(pdf, color)
                ev = "; ".join(detail.matched_evidence[:2])
                pdf.multi_cell(d.CONTENT_W - 10, 4, d.truncate(pdf, "Evidence: " + ev, (d.CONTENT_W - 10) * 3))
            pdf.set_xy(d.MARGIN, y + card_h + 4)

        # ── PAGE 5 — Charts ──────────────────────────────────────────────
        go(pdf, "Page 5 \u00b7 Career Intelligence Charts")
        d.section_title(pdf, "Career Intelligence Charts", d.INDIGO,
                         "Radar, skill distribution, weekly activity and growth trend")
        d.font(pdf, "B", 9.5)
        d.set_text(pdf, d.INK)
        pdf.set_xy(d.MARGIN, pdf.get_y())
        pdf.cell(90, 5, "Readiness Radar", align="C")
        pdf.set_xy(d.MARGIN + 95, pdf.get_y())
        pdf.cell(90, 5, "Activity Category Mix", align="C")
        pdf.ln(6)
        chart_row_y = pdf.get_y()
        radar_axes = [(lbl, getattr(score, key), color) for key, lbl, color in axis_meta]
        d.radar_chart(pdf, d.MARGIN + 45, chart_row_y + 32, 26, radar_axes)
        dist = growth.get("skill_distribution", [])
        donut_segments = [(item["category"], item["count"]) for item in dist] or [("No data", 1)]
        d.donut_chart(pdf, d.MARGIN + 95 + 32, chart_row_y + 32, 26, donut_segments)
        pdf.set_y(chart_row_y + 68)

        d.font(pdf, "B", 9.5)
        d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 5, "Weekly Activity (last 12 weeks)", ln=True)
        weekly = growth.get("weekly_activity", [])
        d.bar_sparkline(pdf, d.MARGIN, pdf.get_y() + 2, d.CONTENT_W, 26, [w["count"] for w in weekly], d.INDIGO,
                         labels=[w["week"][5:] for w in weekly])
        pdf.ln(36)
        d.font(pdf, "B", 9.5)
        d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 5, "Skill Growth Trend (avg. employability score)", ln=True)
        trend = growth.get("weekly_skill_trend", [])
        trend_vals = [t["avg_score"] for t in trend if t["avg_score"] is not None]
        d.line_trend(pdf, d.MARGIN, pdf.get_y() + 2, d.CONTENT_W, 26, trend_vals, d.GREEN)

        # ── PAGE 6 — 30/60/90 Roadmap ────────────────────────────────────
        go(pdf, "Page 6 \u00b7 30/60/90 Day Roadmap")
        d.section_title(pdf, "30 / 60 / 90 Day Learning Roadmap", d.INDIGO,
                         "A phased plan to close the highest-impact skill gaps")
        phases = [
            ("30-Day Goals \u2014 Core Skills", plan["day_30"], d.INDIGO, "Foundation"),
            ("60-Day Goals \u2014 Depth & Breadth", plan["day_60"], d.GREEN, "Development"),
            ("90-Day Goals \u2014 Projects & Credentials", plan["day_90"], d.AMBER, "Mastery"),
        ]
        for title, items, color, sub in phases:
            norm_items = [{"skill": it.get("skill", ""), "why": it.get("why", ""),
                           "resource": (it["resources"][0]["title"] if it.get("resources") else "")}
                          for it in items[:3]]
            if not norm_items:
                norm_items = [{"skill": "Log more activities to unlock this phase", "why": "", "resource": ""}]
            d.timeline_phase(pdf, title, sub, color, norm_items)

        # ── PAGE 7 — Recommendations ─────────────────────────────────────
        go(pdf, "Page 7 \u00b7 Recommendations")
        d.section_title(pdf, "Recommendations", d.PINK,
                         "Concrete next moves: projects, hackathons, certifications, open source")
        cat_meta = [("projects", "Project", d.INDIGO), ("hackathons", "Hackathon", d.PINK),
                    ("certifications", "Certification", d.GREEN), ("open_source", "Open Source", d.AMBER)]
        cards = []
        for key, tag, color in cat_meta:
            for item in opps.get(key, [])[:2]:
                meta = []
                if item.get("difficulty"): meta.append(f"Difficulty: {item['difficulty']}")
                if item.get("frequency"): meta.append(f"Frequency: {item['frequency']}")
                if item.get("cost"): meta.append(f"Cost: {item['cost']}")
                if item.get("provider"): meta.append(f"Provider: {item['provider']}")
                if item.get("description"): meta.append(item["description"])
                if item.get("why"): meta.append(item["why"])
                cards.append({"title": item.get("title", ""), "meta": meta[:3], "color": color, "tag": tag})
        if cards:
            d.recommendation_grid(pdf, cards, cols=2, card_h=34)
        else:
            d.font(pdf, "I", 10)
            d.set_text(pdf, d.MUTED)
            pdf.multi_cell(d.CONTENT_W, 6, "Set a target role to unlock personalised recommendations.")

        # ── PAGE 8 — ATS Report ──────────────────────────────────────────
        go(pdf, "Page 8 \u00b7 ATS Report")
        d.section_title(pdf, "ATS Report", d.GREEN, "Applicant Tracking System keyword and quality analysis")
        d.kpi_grid(pdf, [
            {"label": "ATS Score", "value_str": f"{ats['ats_score']:.0f}%", "color": d.tier_color(ats['ats_score'])},
            {"label": "Resume Strength", "value_str": f"{ats['resume_strength']:.0f}%",
             "color": d.tier_color(ats['resume_strength'])},
            {"label": "Interview Readiness", "value_str": f"{ats['interview_ready']:.0f}%",
             "color": d.tier_color(ats['interview_ready'])},
        ], cols=3, card_h=28)
        pdf.ln(8)
        if ats.get("missing_keywords"):
            d.font(pdf, "B", 10)
            d.set_text(pdf, d.INK)
            pdf.cell(d.CONTENT_W, 6, f"Missing Keywords ({len(ats['missing_keywords'])})", ln=True)
            pdf.ln(1)
            x, y = d.MARGIN, pdf.get_y()
            for kw in ats["missing_keywords"][:14]:
                w = d.badge(pdf, x, y, kw, d.AMBER, filled=False) + 3
                if x + w > d.PAGE_W - d.MARGIN:
                    x = d.MARGIN
                    y += 8
                else:
                    x += w
            pdf.set_xy(d.MARGIN, y + 10)
        if ats.get("improvements"):
            d.divider(pdf)
            d.font(pdf, "B", 10.5)
            d.set_text(pdf, d.INK)
            pdf.cell(d.CONTENT_W, 6, "Resume Improvement Suggestions", ln=True)
            pdf.ln(1)
            for tip in ats["improvements"][:4]:
                pc = d.RED if tip["priority"] == "High" else d.AMBER
                y = pdf.get_y()
                bw = d.badge(pdf, d.MARGIN, y, tip["priority"], pc)
                pdf.set_xy(d.MARGIN + bw + 3, y - 0.2)
                d.font(pdf, "B", 9)
                d.set_text(pdf, d.INK)
                pdf.cell(50, 5.4, tip["area"], ln=False)
                pdf.ln(6)
                d.font(pdf, "", 8.5)
                d.set_text(pdf, d.MUTED)
                pdf.set_x(d.MARGIN)
                pdf.multi_cell(d.CONTENT_W, 4.4, tip["action"])
                pdf.ln(2)

        # ── PAGE 9 — Recruiter Summary ───────────────────────────────────
        go(pdf, "Page 9 \u00b7 Recruiter Summary")
        d.section_title(pdf, "Recruiter Summary", d.INDIGO, "One-page executive overview for hiring managers")
        tier_color = d.GREEN if recruiter["overall_tier"] == "Strong" else (
            d.AMBER if recruiter["overall_tier"] == "Developing" else d.RED)
        y = pdf.get_y()
        d.card_bg(pdf, d.MARGIN, y, d.CONTENT_W, 22, fill=d.SURFACE)
        pdf.set_xy(d.MARGIN + 6, y + 4)
        d.font(pdf, "B", 12)
        d.set_text(pdf, d.INK)
        pdf.cell(90, 7, f"Overall Verdict: {recruiter['overall_tier']}", ln=False)
        d.badge(pdf, d.PAGE_W - d.MARGIN - 30, y + 5, f"{score.overall:.0f}/100", tier_color)
        pdf.set_xy(d.MARGIN + 6, y + 12)
        d.font(pdf, "", 8.5)
        d.set_text(pdf, d.MUTED)
        pdf.multi_cell(d.CONTENT_W - 12, 4.4, f"Next action: {recruiter['next_action']}")
        pdf.set_xy(d.MARGIN, y + 26)

        col_w = (d.CONTENT_W - 6) / 2
        sy = pdf.get_y()
        d.font(pdf, "B", 10)
        d.set_text(pdf, d.GREEN)
        pdf.set_xy(d.MARGIN, sy)
        pdf.cell(col_w, 6, "Top Strengths", ln=True)
        d.font(pdf, "", 8.7)
        d.set_text(pdf, d.INK)
        for s in recruiter["top_strengths"] or ["Not enough data yet"]:
            pdf.set_x(d.MARGIN)
            pdf.multi_cell(col_w, 4.6, "\u2022 " + s)
        strengths_end_y = pdf.get_y()

        d.font(pdf, "B", 10)
        d.set_text(pdf, d.RED)
        pdf.set_xy(d.MARGIN + col_w + 6, sy)
        pdf.cell(col_w, 6, "Improvement Areas", ln=True)
        d.font(pdf, "", 8.7)
        d.set_text(pdf, d.INK)
        for a in recruiter["improvement_areas"] or ["None identified"]:
            pdf.set_xy(d.MARGIN + col_w + 6, pdf.get_y())
            pdf.multi_cell(col_w, 4.6, "\u2022 " + a)
        areas_end_y = pdf.get_y()
        pdf.set_y(max(strengths_end_y, areas_end_y) + 4)

        d.divider(pdf)
        d.font(pdf, "B", 10)
        d.set_text(pdf, d.INK)
        pdf.cell(d.CONTENT_W, 6, "Top Skills", ln=True)
        x, y = d.MARGIN, pdf.get_y()
        for sk in recruiter["top_skills"][:6] or ["No skills logged yet"]:
            w = d.badge(pdf, x, y, sk, d.INDIGO) + 3
            if x + w > d.PAGE_W - d.MARGIN:
                x = d.MARGIN
                y += 8
            else:
                x += w

        # ── PAGE 10 — Closing ────────────────────────────────────────────
        go(pdf, "Page 10 \u00b7 Closing")
        d.set_fill(pdf, d.INDIGO)
        pdf.rect(0, 0, d.PAGE_W, d.PAGE_H, "F")
        pdf.set_xy(0, 110)
        d.font(pdf, "B", 22)
        d.set_text(pdf, d.WHITE)
        pdf.cell(d.PAGE_W, 12, "Thank You", align="C")
        pdf.set_xy(0, 124)
        d.font(pdf, "", 10.5)
        d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 6, f"for reviewing {candidate_name.split()[0]}'s Career Intelligence Portfolio", align="C")
        d.set_draw(pdf, (129, 140, 248))
        pdf.line(70, 150, 140, 150)
        pdf.set_xy(0, 158)
        d.font(pdf, "", 9)
        d.set_text(pdf, (199, 210, 254))
        pdf.cell(d.PAGE_W, 5, "Generated using ISIS \u2014 Invisible Skill Intelligence System", align="C")
        pdf.set_xy(0, 165)
        pdf.cell(d.PAGE_W, 5, f"Career Intelligence Platform  \u2022  {today_str}", align="C")

        buf = io.BytesIO()
        pdf.output(buf)
        buf.seek(0)

    except Exception:
        logger.exception("career_portfolio_pdf_render_failed", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("Could not render portfolio PDF. Please try again.")}), 500

    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"ISIS_Career_Portfolio_{target_role.replace(' ','_')}.pdf")


@app.route("/career/growth_data")
@login_required
def career_growth_data():
    """Returns chart-ready growth tracker data for the dashboard."""
    user_id = authenticated_user_id()
    activities = db.get_user_activities(user_id)
    data = growth_tracker.compute_growth_data(activities)
    return jsonify(data)


# ---------------------------------------------------------------------------
# AI Career Copilot
# ---------------------------------------------------------------------------
# Routes are deliberately thin — all context building, prompt construction,
# Gemini calling, and local fallback logic lives in services/ai_copilot.py.

@app.route("/copilot/ask", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def copilot_ask():
    """
    POST /copilot/ask  {"message": "..."}
    Returns the Copilot's answer, grounded only in the user's own data.
    """
    user_id = authenticated_user_id()
    data = request.get_json(silent=True) or {}

    try:
        message = validators.validate_string_length(
            data.get("message", ""), "Question", max_length=2000, min_length=1
        )
    except validators.ValidationError as e:
        return jsonify({"status": "error", "message": e.message}), 400

    try:
        result = ai_copilot.ask(user_id, message, gemini_client=client)
    except Exception:
        logger.exception("copilot_ask_failed", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("The Copilot couldn't respond. Please try again.")}), 500

    return jsonify({"status": "ok", **result})


@app.route("/copilot/history")
@login_required
def copilot_history():
    """GET /copilot/history — returns recent conversation history for the current user."""
    user_id = authenticated_user_id()
    try:
        history = copilot_repository.get_history(user_id)
    except Exception:
        logger.exception("copilot_history_failed", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("Could not load conversation history.")}), 500
    return jsonify({"status": "ok", "history": history})


@app.route("/copilot/clear", methods=["POST"])
@login_required
def copilot_clear():
    """POST /copilot/clear — clears the current user's Copilot conversation history."""
    user_id = authenticated_user_id()
    try:
        copilot_repository.clear(user_id)
        ai_copilot.invalidate_context_cache(user_id)
    except Exception:
        logger.exception("copilot_clear_failed", extra={"user_id": user_id})
        return jsonify({"status": "error", "message": _("Could not clear conversation history.")}), 500
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

# Runs on import, not just under `python app.py` — this matters because a
# production WSGI server (gunicorn, per the Dockerfile) imports this module
# as `app:app` and never executes the `if __name__ == "__main__"` block
# below, so init_db() has to run here to guarantee the schema (tables +
# indexes) exists before the first request. Idempotent (CREATE TABLE/INDEX
# IF NOT EXISTS), so safe to run on every worker process's startup.
logger.info("isis_startup_initializing_database")
db.init_db()

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    host = os.environ.get("ISIS_HOST", "127.0.0.1")
    port = int(os.environ.get("ISIS_PORT", "5000"))

    if debug_mode:
        logger.warning(
            "isis_starting_in_debug_mode",
            extra={"note": "Never enable FLASK_DEBUG in production — exposes the interactive debugger/RCE."}
        )
    logger.info("isis_starting_server", extra={"host": host, "port": port, "debug": debug_mode})
    app.run(debug=debug_mode, host=host, port=port)
