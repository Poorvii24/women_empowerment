"""
app.py - Main Flask application for the ISIS (Invisible Skill Intelligence System) backend.

Endpoints:
    POST /analyze_activity     - Accept a raw activity text and return mapped professional skills
    GET  /dashboard_metrics    - Return aggregated skill metrics for the dashboard charts
    GET  /activities           - List past recorded activities for a user
    GET  /health               - Health check
"""
import io
import json
import os
import re
import sqlite3
import urllib.parse
from flask import (
    Flask, request, jsonify, send_from_directory,
    render_template, redirect, url_for, flash, session
)
from flask_cors import CORS
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_babel import Babel, _
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from google.genai import types
import db

# Serve static files (styles.css, script.js) from the current directory
app = Flask(__name__, static_folder=".", static_url_path="",
            template_folder=".")  # serve HTML templates via render_template
app.secret_key = os.environ.get("ISIS_SECRET_KEY", "isis-dev-secret-change-in-production")
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_SUPPORTED_LOCALES'] = ['en', 'hi', 'kn']

CORS(app)  # Allow cross-origin requests from the frontend

# ---------------------------------------------------------------------------
# Flask-Babel Setup
# ---------------------------------------------------------------------------
def get_locale():
    # If a user explicitly sets a language in the session, use it
    if 'lang' in session:
        return session['lang']
    # Otherwise guess from browser headers
    return request.accept_languages.best_match(app.config['BABEL_SUPPORTED_LOCALES'])

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

# Initialize Gemini Client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))

# Load the professional skill reference dataset once at startup
SKILLS_PATH = os.path.join(os.path.dirname(__file__), "skills.json")
with open(SKILLS_PATH, "r") as f:
    SKILL_DATA = json.load(f)

SKILL_MAPPINGS = SKILL_DATA["skill_mappings"]
LEADERSHIP_CATEGORIES = SKILL_DATA["leadership_categories"]


# ---------------------------------------------------------------------------
# Analytics Engine - Zero-Shot Semantic Keyword Mapping
# ---------------------------------------------------------------------------

def map_activity_to_skill(activity_text: str) -> dict:
    """
    Maps a raw activity description to its closest professional skill via
    keyword-weight matching against the O*NET skill reference dataset.

    Returns a structured result dict with:
        - mapped_skill
        - onet_category
        - leadership_category
        - skill_magnitude  (weighted score 0–100)
        - market_value
        - transferable_skill (alias)
        - leadership_index  (category-weighted score)
    """
    text = activity_text.lower()
    best_match = None
    best_score = 0

    for skill in SKILL_MAPPINGS:
        score = 0
        for keyword in skill["keywords"]:
            # Partial/stem match using regex
            if re.search(keyword, text):
                score += 1

        if score > best_score:
            best_score = score
            best_match = skill

    # Default fallback if nothing matches
    if best_match is None or best_score == 0:
        best_match = {
            "professional_skill": "General Administrative Support",
            "onet_category": "Office & Administrative Support",
            "leadership_category": "Team Coordination",
            "market_value": "Medium",
            "base_magnitude": 60
        }

    # Calculate weighted leadership index
    category_weight = LEADERSHIP_CATEGORIES.get(
        best_match["leadership_category"], {}
    ).get("weight", 1.0)

    # Skill magnitude: base score boosted by keyword match density and category weight
    keyword_count = len(best_match["keywords"])
    density_bonus = min(best_score / keyword_count, 1.0) * 15
    skill_magnitude = min(100, round(best_match["base_magnitude"] + density_bonus, 2))
    leadership_index = min(100, round(skill_magnitude * category_weight, 2))

    return {
        "transferable_skill": best_match["professional_skill"],
        "mapped_skill": best_match["professional_skill"],
        "onet_category": best_match["onet_category"],
        "leadership_category": best_match["leadership_category"],
        "skill_magnitude": skill_magnitude,
        "leadership_index": leadership_index,
        "market_value": best_match["market_value"],
        "matched_keywords": best_score
    }


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
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")
        # Validation
        if not username or len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
        elif not re.match(r'^[a-zA-Z0-9_]+$', username):
            flash("Username may only contain letters, numbers, and underscores.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            pw_hash = generate_password_hash(password)
            user_id = db.create_user(username, pw_hash)
            if user_id is None:
                flash("Username already taken. Please choose another.", "error")
            else:
                flash("Account created! Please sign in.", "success")
                return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------



@app.route("/")
@login_required
def index():
    """Serves the main frontend dashboard."""
    # Serve using render_template instead of send_from_directory to enable Babel tags 
    # but still point to index.html in the root folder via template_folder="."
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    """Simple health check endpoint."""
    return jsonify({"status": "OK", "message": "ISIS backend is running."}), 200


@app.route("/analyze_activity", methods=["POST"])
@login_required
def analyze_activity():
    """
    POST /analyze_activity
    Request Body (JSON):
        {
            "activity": "I managed the household budget and planned weekly meals",
            "user_id": "user_001"   (optional, defaults to 'default_user')
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
    # Always use the authenticated user's ID rather than a client-supplied value
    user_id = str(current_user.get_id()) if current_user.is_authenticated else "default_user"

    if not user_input or len(user_input) < 5:
        return jsonify({"status": "error", "message": "Activity description is required and must be descriptive."}), 400

    if not os.environ.get("GEMINI_API_KEY"):
        return jsonify({"status": "error", "message": "Server missing GEMINI_API_KEY environment variable."}), 500

    lang_code = get_locale()
    lang_map = {
        'en': 'English',
        'hi': 'Hindi (हिंदी)',
        'kn': 'Kannada (ಕನ್ನಡ)'
    }
    target_language = lang_map.get(str(lang_code), 'English')

    # -------------------------------------------------------------------------
    # The High-Precision Gemini Prompt
    # -------------------------------------------------------------------------
    prompt = f"""
You are a professional career analyst specializing in translating unpaid and informal labor
into corporate-standard credentials. Analyze the following activity and return a precise JSON.

IMPORTANT MULTI-LANGUAGE INSTRUCTION: 
You MUST generate the `professional_title`, `career_equivalency`, `resume_bullet`, 
`mapped_skill`, and items inside `skills_mapped` in **{target_language}**. 
When translating into {target_language} (especially Kannada or Hindi), use standard, everyday, regional terms that are easily understood by rural users. Avoid overly formal or complex academic translations. The JSON keys themselves must remain strictly in English.

CAREER EQUIVALENCY LOGIC:
Instead of a fixed title, you MUST select a corporate role for the `career_equivalency` field based on the input's complexity. Base your decision on the number of people managed and the total budget/resources handled:
  * **Low Complexity** (e.g., daily chores, no budget) -> "Administrative Assistant"
  * **Medium Complexity** (e.g., budget planning, event coordination, small teams) -> "Operations Coordinator" or "Project Lead"
  * **High Complexity** (e.g., managing community funds, leading large teams, crisis mediation) -> "Operations Manager" or "Strategic Resource Analyst"

OPPORTUNITY ENGINE LOGIC:
Based on ONLY the user's ACTUAL activity input (which could be healthcare, finance, childcare, education, agriculture, crafts, etc.), you MUST suggest three HYPER-SPECIFIC and CONTEXTUALLY ACCURATE opportunities. You are FORBIDDEN from generating generic or catering-related responses unless the user explicitly mentions cooking or food.

CRITICAL DEMO DATA MAPPING:
To ensure perfect demonstration, you MUST follow these exact mappings if the user's input matches the domain:
  * If the input is Health-related: The `job_role` MUST be "Public Health Outreach Coordinator" and `startup_idea` MUST be "Mobile Health & First-Aid Training Center". Ensure the `collaboration_match` is a relevant health partnership.
  * If the input is Logistics-related: The `job_role` MUST be "Supply Chain Coordinator" and `startup_idea` MUST be "Village-to-City Agri-Logistics Service". Ensure the `collaboration_match` is a relevant logistics/transport partnership.

For all other domains:
  * **Startup Idea**: A micro-business concept directly tied to the domain they described (e.g., if finance → "Micro-savings coaching group")
  * **Collaboration Match**: A partnership idea uniquely suited to the domain they described.
  * **Job Role**: A directly employable role matching their demonstrated skills in that domain.

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

    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        parsed_result = json.loads(response.text)
        gemini_ok = True

    except Exception as e:
        print(f"[Gemini API Error]: {str(e)}")

    # -------------------------------------------------------------------------
    # Extract & Validate Fields (Gemini OR local fallback)
    # -------------------------------------------------------------------------
    if gemini_ok:
        mapped_skill        = str(parsed_result.get("professional_title", "General Administration"))
        career_equivalency  = str(parsed_result.get("career_equivalency", "Matches Administrative Coordinator"))
        resume_snippet      = str(parsed_result.get("resume_bullet", f"Demonstrated expertise in {mapped_skill}."))
        leadership_index    = validate_and_clamp(parsed_result.get("leadership_index"), 75)
        employability_score = validate_and_clamp(parsed_result.get("employability_score"), 75)
        skills_mapped       = parsed_result.get("skills_mapped", [])[:5]  # Cap at 5
        onet_category       = str(parsed_result.get("onet_category", "Office & Administrative Support"))
        leadership_category = str(parsed_result.get("leadership_category", "Team Coordination"))

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
        # Local fallback: build radar from keyword engine
        fallback = map_activity_to_skill(user_input)
        mapped_skill        = fallback["mapped_skill"]
        career_equivalency  = "Matches Administrative Coordinator"
        resume_snippet      = f"Demonstrated expertise in {mapped_skill} through hands-on experience."
        leadership_index    = validate_and_clamp(fallback["leadership_index"], 70)
        employability_score = validate_and_clamp(fallback["skill_magnitude"], 70)
        skills_mapped       = []
        onet_category       = fallback["onet_category"]
        leadership_category = fallback["leadership_category"]

        # Derive 5-point radar from category weight
        base = validate_and_clamp(fallback["skill_magnitude"], 60)
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
        resume_snippet=resume_snippet
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
    collaboration_match_val = str(raw_opps.get("collaboration_match") or raw_opps.get("collaboration") or "Partner with Local PHC / District Health Office")
    job_role_val            = str(raw_opps.get("job_role")            or raw_opps.get("specific_job_roles") or "Public Health Outreach Coordinator")

    raw_growth_skill = raw_learning.get("skill_to_learn") if isinstance(raw_learning, dict) else None
    growth_skill_val = str(raw_growth_skill or "Digital Marketing")
    learning_url_val = "https://www.youtube.com/embed/Xv1tM_pX22Y"  # verified Google Digital Garage

    market_opps = {
        # flat keys — primary surface area read by script.js
        "startup_idea":        startup_idea_val,
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
        "collaboration_match":  market_opps["collaboration_match"],
        "job_role":             market_opps["job_role"],
        "growth_skill":         market_opps["growth_skill"],
        "learning_url":         market_opps["learning_url"],
        # Real external links built from the AI-returned values
        "job_link":             build_job_link(market_opps["job_role"]),
        "learning_link":        build_learning_link(market_opps["growth_skill"]),
        "learning_path":        learning_path,
        "matches":              sanitized_matches,
        "source":               "gemini" if gemini_ok else "local_fallback"
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
    """
    supported = app.config.get('BABEL_SUPPORTED_LOCALES', ['en', 'hi', 'kn'])
    if lang in supported:
        session['lang'] = lang
        session.modified = True
    return redirect(request.referrer or url_for('index'))


@app.route("/dashboard_metrics", methods=["GET"])
def dashboard_metrics():
    """
    GET /dashboard_metrics?user_id=default_user

    Returns aggregated data for radar chart rendering:
        - leadership_radar: data per leadership category (for Leadership Index chart)
        - employability_score: computed overall employability score
        - total_activities: number of activities logged
        - recent_activities: last 5 entries
    """
    user_id = request.args.get("user_id", "default_user")
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
def list_activities():
    """
    GET /activities?user_id=default_user
    Returns the full list of logged activities for a user.
    """
    user_id = request.args.get("user_id", "default_user")
    activities = db.get_user_activities(user_id)
    return jsonify({"status": "success", "activities": activities}), 200


@app.route("/history", methods=["GET"])
@login_required
def history():
    """
    GET /history?user_id=default_user
    Renders every saved activity in a clean HTML table.
    """
    user_id = request.args.get("user_id", "default_user")
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

@app.route("/generate_pdf")
@login_required
def generate_pdf():
    """
    GET /generate_pdf?user_id=<id>
    Generates and downloads a professional portfolio PDF for the user.
    Bullets are deduplicated at the SQL level (DISTINCT) AND in Python
    (seen_bullets set), so repeated activity submissions never produce
    duplicate lines in the final document.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        return jsonify({"error": "fpdf2 not installed. Run: pip install fpdf2"}), 500

    user_id = request.args.get("user_id", str(current_user.get_id()))

    # ── 1. Fetch unique bullets from DB (DISTINCT at SQL level) ──────────
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT
            resume_snippet,
            mapped_skill,
            career_equivalency,
            skills_mapped,
            employability_score,
            leadership_index
        FROM activities
        WHERE user_id = ?
          AND resume_snippet IS NOT NULL
          AND TRIM(resume_snippet) != ''
        ORDER BY employability_score DESC
        LIMIT 10
    """, (user_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # ── 2. Build PDF ───────────────────────────────────────────────────────
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Header ───────────────────────────────────────────────────────────
    pdf.set_fill_color(99, 102, 241)   # indigo
    pdf.rect(0, 0, 210, 38, 'F')
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 12, "ISIS Professional Portfolio", ln=True, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, "Invisible Skill Intelligence System — Certified Skill Report", ln=True, align="C")
    pdf.ln(14)

    # ── Section: Resume Bullets ────────────────────────────────────────────
    pdf.set_text_color(40, 40, 40)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_fill_color(240, 240, 255)
    pdf.cell(0, 10, "  Professional Resume Bullets", ln=True, fill=True)
    pdf.ln(3)

    seen_bullets = set()   # Python-level second dedup guard

    if rows:
        for row in rows:
            bullet = str(row.get("resume_snippet") or "").strip()
            skill  = str(row.get("mapped_skill")   or "").strip()

            # ── Skip empty or already-seen bullets ───────────────────────
            if not bullet or bullet in seen_bullets:
                continue
            seen_bullets.add(bullet)

            # Bullet row
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(99, 102, 241)
            pdf.cell(6, 7, chr(149), ln=False)   # bullet dot
            pdf.set_text_color(30, 30, 30)
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 7, bullet)

            # Skill tag underneath
            if skill:
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(120, 120, 120)
                pdf.cell(0, 6, f"  Skill area: {skill}", ln=True)
            pdf.ln(2)
    else:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(140, 140, 140)
        pdf.cell(0, 10, "No activities recorded yet. Submit your first activity to generate bullets.", ln=True)

    # ── Section: Summary Stats ────────────────────────────────────────────
    if rows:
        avg_emp = round(sum(r.get("employability_score") or 0 for r in rows) / len(rows), 1)
        avg_li  = round(sum(r.get("leadership_index")   or 0 for r in rows) / len(rows), 1)

        pdf.ln(4)
        pdf.set_fill_color(240, 255, 245)
        pdf.set_text_color(40, 40, 40)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 10, "  Your Scores", ln=True, fill=True)
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, f"  Employability Score : {avg_emp} / 100", ln=True)
        pdf.cell(0, 8, f"  Leadership Index    : {avg_li} / 100", ln=True)
        pdf.cell(0, 8, f"  Unique Skills Mapped: {len(seen_bullets)}", ln=True)

    # ── Footer ────────────────────────────────────────────────────────────
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 10, "Generated by ISIS — Women Empowerment Skills Platform", align="C")

    # ── Stream to browser ─────────────────────────────────────────────────
    buf = io.BytesIO()
    pdf.output(buf)
    buf.seek(0)

    from flask import send_file
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="ISIS_Professional_Portfolio.pdf"
    )


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[ISIS] Initializing database...")
    db.init_db()
    print("[ISIS] Starting Flask server on http://127.0.0.1:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
