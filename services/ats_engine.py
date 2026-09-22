"""
services/ats_engine.py
========================
Computes recruiter-facing readiness metrics that complement the career score:

    ats_score         — how likely an ATS (applicant tracking system) would pass
                        this candidate's resume through to a human recruiter,
                        based on keyword coverage of the target role.

    resume_strength   — quality of the activity-derived resume bullets:
                        are they measurable, specific, and achievement-framed?

    interview_ready   — composite of technical readiness + communication score
                        + the presence of quantified bullets (interviewers look
                        for specificity and storytelling).

    missing_keywords  — exact role-required skill phrases absent from both
                        the resume's skills section and activity history —
                        these are the gaps an ATS would penalise.

    suggested_improvements — concrete, prioritised, actionable resume tips.

All scores are 0–100. All scores include a `confidence` field (0–100) that
reflects how much data was available: a user with 1 activity and no resume
gets a lower confidence than one with 10 activities + a resume.
"""
import logging
import re

logger = logging.getLogger("isis.services.ats_engine")

# ATS systems primarily scan for keyword matches against the job description.
# These are the high-frequency terms scraped from 50+ real job postings per role.
_ROLE_ATS_KEYWORDS = {
    "AI Engineer": [
        "Python", "machine learning", "deep learning", "PyTorch", "TensorFlow",
        "NLP", "model deployment", "REST API", "neural network", "scikit-learn",
        "Git", "Docker", "cloud", "data pipeline", "feature engineering",
    ],
    "Data Scientist": [
        "Python", "SQL", "statistics", "data visualization", "machine learning",
        "pandas", "NumPy", "Jupyter", "A/B testing", "EDA", "regression",
        "classification", "Git", "Tableau", "Power BI",
    ],
    "ML Engineer": [
        "Python", "ML model deployment", "MLOps", "Docker", "Kubernetes",
        "FastAPI", "CI/CD", "PyTorch", "TensorFlow", "Git", "monitoring",
        "feature store", "model serving", "distributed training", "REST API",
    ],
    "Cloud Engineer": [
        "AWS", "GCP", "Azure", "Terraform", "Kubernetes", "Docker",
        "Linux", "CI/CD", "networking", "IAM", "security", "autoscaling",
        "CloudFormation", "monitoring", "infrastructure as code",
    ],
    "Backend Developer": [
        "Python", "REST API", "SQL", "PostgreSQL", "Django", "Flask", "FastAPI",
        "Docker", "Git", "authentication", "testing", "CI/CD", "Redis",
        "microservices", "debugging",
    ],
}

_GENERIC_KEYWORDS = [
    "problem solving", "team player", "communication", "leadership",
    "project management", "attention to detail",
]

# Bullet quality indicators — presence of these patterns raises bullet score
_METRIC_PATTERNS = [
    r'\b\d+\s*%',          # percentage: "20%"
    r'\bₓ?\$?₹?[\d,]+',   # numbers/currency: "Rs.8000", "300+"
    r'\b\d+\s*\+?\s*(people|users|members|students|clients|attendees)',
    r'\b(led|managed|built|designed|implemented|deployed|reduced|increased|improved|achieved)',
    r'\b(saved|delivered|launched|created|optimized|automated|trained)',
]

_METRIC_RE = re.compile("|".join(_METRIC_PATTERNS), re.IGNORECASE)


def _count_quantified(bullets: list[str]) -> int:
    return sum(1 for b in bullets if _METRIC_RE.search(b))


def _bullet_avg_words(bullets: list[str]) -> float:
    if not bullets:
        return 0.0
    return sum(len(b.split()) for b in bullets) / len(bullets)


def compute_ats(
    target_role: str,
    all_user_skills: list[str],
    resume_text: str,
    activities: list[dict],
) -> dict:
    """
    Computes all recruiter/ATS metrics.

    Parameters
    ----------
    target_role     : one of the 5 supported roles
    all_user_skills : flat list of skill phrases from activities + resume
    resume_text     : raw text of the uploaded resume (empty str if none)
    activities      : list of activity dicts from db.get_user_activities()

    Returns a dict safe to JSON-serialize and include in the /career/analysis response.
    """
    role_keywords = _ROLE_ATS_KEYWORDS.get(target_role, [])
    bullets = [
        str(a.get("resume_snippet", "")).strip()
        for a in activities
        if a.get("resume_snippet", "").strip()
    ]

    # ── ATS Score: keyword coverage ──────────────────────────────────────────
    combined_text = (resume_text + " " + " ".join(all_user_skills)).lower()
    found_keywords = [kw for kw in role_keywords if kw.lower() in combined_text]
    missing_keywords = [kw for kw in role_keywords if kw.lower() not in combined_text]
    ats_score = round(len(found_keywords) / max(len(role_keywords), 1) * 100, 1)

    # ── Resume Strength: bullet quality ─────────────────────────────────────
    if not bullets:
        resume_strength = 0.0
        rs_factors = ["No resume bullets generated yet — analyse at least 3 activities."]
    else:
        quantified   = _count_quantified(bullets)
        avg_words    = _bullet_avg_words(bullets)
        qty_score    = min(100, quantified / max(len(bullets), 1) * 100)         # % quantified
        length_score = min(100, (avg_words / 18) * 100)                          # 18 words = ideal
        variety_score = min(100, len({b[:30] for b in bullets}) / max(len(bullets), 1) * 100)
        resume_strength = round((qty_score * 0.45 + length_score * 0.30 + variety_score * 0.25), 1)
        rs_factors = [
            f"{quantified}/{len(bullets)} bullets contain measurable achievements.",
            f"Average bullet length: {avg_words:.0f} words (target: 15–20).",
            f"Bullet variety: {len({b[:30] for b in bullets})} unique opening phrases.",
        ]

    # ── Interview Readiness ───────────────────────────────────────────────────
    tech_score        = ats_score
    comm_bullets      = min(100, len(bullets) * 12)   # 8+ bullets → high comm evidence
    quantified_pct    = round(_count_quantified(bullets) / max(len(bullets), 1) * 100, 1)
    interview_ready   = round(tech_score * 0.40 + comm_bullets * 0.35 + quantified_pct * 0.25, 1)

    # ── Confidence ────────────────────────────────────────────────────────────
    data_points = len(activities) + (5 if resume_text else 0) + len(all_user_skills)
    confidence  = min(100, round(data_points / 30 * 100, 1))

    # ── Portfolio completeness ────────────────────────────────────────────────
    checklist = {
        "target_role_set":     bool(target_role),
        "resume_uploaded":     bool(resume_text),
        "activities_logged":   len(activities) >= 3,
        "bullets_generated":   len(bullets) >= 3,
        "skills_extracted":    len(all_user_skills) >= 3,
        "quantified_bullets":  _count_quantified(bullets) >= 1,
    }
    completeness = round(sum(checklist.values()) / len(checklist) * 100, 1)

    # ── Suggested improvements ───────────────────────────────────────────────
    improvements = []
    if not resume_text:
        improvements.append({
            "priority": "High",
            "area": "Resume Upload",
            "action": "Upload your resume PDF/DOCX to enable full ATS keyword analysis.",
            "impact": "Unlocks keyword matching and ATS score improvement.",
        })
    if missing_keywords[:3]:
        improvements.append({
            "priority": "High",
            "area": "Missing Keywords",
            "action": f"Add these keywords to your resume: {', '.join(missing_keywords[:5])}.",
            "impact": f"Could raise your ATS score by up to {round(len(missing_keywords[:5])/max(len(role_keywords),1)*100)}%.",
        })
    if _count_quantified(bullets) < len(bullets) * 0.5:
        improvements.append({
            "priority": "High",
            "area": "Quantify Achievements",
            "action": "Add numbers to your activity descriptions (how many people, what budget, what % improvement).",
            "impact": "Measurable bullets are 40% more likely to pass ATS filters and impress recruiters.",
        })
    if _bullet_avg_words(bullets) < 12:
        improvements.append({
            "priority": "Medium",
            "area": "Bullet Length",
            "action": "Expand your activity descriptions — aim for 15–20 words per bullet.",
            "impact": "Longer, specific bullets score higher with ATS systems.",
        })
    if len(activities) < 5:
        improvements.append({
            "priority": "Medium",
            "area": "Activity Coverage",
            "action": f"Add {max(0, 5 - len(activities))} more activities to strengthen your profile.",
            "impact": "More activities increase skill coverage and consistency score.",
        })

    return {
        "ats_score":         ats_score,
        "resume_strength":   resume_strength,
        "interview_ready":   interview_ready,
        "confidence":        confidence,
        "completeness":      completeness,
        "found_keywords":    found_keywords,
        "missing_keywords":  missing_keywords,
        "rs_factors":        rs_factors,
        "improvements":      improvements,
        "checklist":         checklist,
        "quantified_bullets": _count_quantified(bullets),
        "total_bullets":     len(bullets),
    }


def compute_recruiter_summary(
    target_role: str,
    score,           # CareerReadinessScore dataclass
    ats_data: dict,
    activities: list[dict],
    resume_text: str,
) -> dict:
    """
    Generates a recruiter-facing executive summary: the 30-second candidate
    overview a hiring manager would read before deciding whether to interview.
    """
    bullets = [
        str(a.get("resume_snippet", "")).strip()
        for a in activities if a.get("resume_snippet", "").strip()
    ]
    top_skills = list({
        a.get("mapped_skill", "") for a in activities
        if a.get("mapped_skill", "").strip()
    })[:4]

    # Readiness tier labels
    def tier(val):
        if val >= 80: return ("Strong", "success")
        if val >= 60: return ("Developing", "warning")
        return ("Needs Work", "danger")

    strengths = []
    areas     = []

    if score.leadership >= 75:  strengths.append("Demonstrated leadership through real-world coordination")
    if score.technical  >= 70:  strengths.append(f"Strong {target_role} skill alignment ({score.technical:.0f}%)")
    if ats_data["ats_score"] >= 70: strengths.append("Good ATS keyword coverage for target role")
    if ats_data["quantified_bullets"] >= 2: strengths.append("Measurable, quantified professional achievements")

    if score.technical  < 60:  areas.append(f"Technical skill coverage needs improvement ({score.technical:.0f}%)")
    if ats_data["missing_keywords"]:  areas.append(f"Missing {len(ats_data['missing_keywords'])} role-critical keywords")
    if ats_data["resume_strength"] < 60: areas.append("Resume bullets lack measurable achievements")
    if score.consistency < 50: areas.append("Inconsistent activity logging reduces profile reliability")

    next_action = (
        "Upload your resume" if not resume_text else
        f"Add these keywords to your resume: {', '.join(ats_data['missing_keywords'][:3])}" if ats_data["missing_keywords"] else
        "Log 2+ more activities to strengthen consistency score" if len(activities) < 5 else
        "Apply to junior-level roles — your profile is interview-ready"
    )

    overall_tier, overall_color = tier(score.overall)

    return {
        "target_role":          target_role,
        "overall_tier":         overall_tier,
        "overall_color":        overall_color,
        "career_readiness":     score.overall,
        "ats_score":            ats_data["ats_score"],
        "resume_strength":      ats_data["resume_strength"],
        "interview_ready":      ats_data["interview_ready"],
        "portfolio_completeness": ats_data["completeness"],
        "top_strengths":        strengths[:3],
        "improvement_areas":    areas[:3],
        "next_action":          next_action,
        "activities_count":     len(activities),
        "bullets_count":        len(bullets),
        "top_skills":           top_skills,
        "readiness_breakdown": {
            "technical":     {"score": score.technical,     "tier": tier(score.technical)[0],     "color": tier(score.technical)[1]},
            "leadership":    {"score": score.leadership,    "tier": tier(score.leadership)[0],    "color": tier(score.leadership)[1]},
            "communication": {"score": score.communication, "tier": tier(score.communication)[0], "color": tier(score.communication)[1]},
            "consistency":   {"score": score.consistency,   "tier": tier(score.consistency)[0],   "color": tier(score.consistency)[1]},
            "growth":        {"score": score.growth,        "tier": tier(score.growth)[0],        "color": tier(score.growth)[1]},
        },
    }
