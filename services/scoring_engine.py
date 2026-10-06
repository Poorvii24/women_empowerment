"""
services/scoring_engine.py
============================
Computes a multi-axis Career Readiness Score from a user's activity history
and skill gap analysis result.

Six scores are produced:
    overall          — weighted average of the five axis scores below (0–100)
    technical        — how well the user's demonstrated skills cover the
                       target role's required skills (derived from gap analysis)
    leadership       — average leadership_index across all activities,
                       scaled to 0–100
    communication    — proxy: activity count × resume bullet quality score
    consistency      — regularity of activity logging (how many distinct
                       weeks had at least one activity in the last 12 weeks)
    growth           — improvement in employability_score over time
                       (later activities vs earlier activities)

Every score ships with a structured explanation block containing:
    summary          — one-sentence plain-English reason for the score
    contributing_factors — list of specific data points that drove the number
    matched_evidence — activities/bullets that positively contributed
    missing_evidence — what would raise the score further
    confidence       — 0–100, how much data backed this score
"""
import datetime
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("isis.services.scoring_engine")

_WEIGHTS = {
    "technical":     0.30,
    "leadership":    0.25,
    "communication": 0.15,
    "consistency":   0.15,
    "growth":        0.15,
}


@dataclass
class AxisExplanation:
    summary: str
    contributing_factors: list
    matched_evidence: list
    missing_evidence: list
    confidence: float


@dataclass
class CareerReadinessScore:
    overall: float
    technical: float
    leadership: float
    communication: float
    consistency: float
    growth: float
    explanations: dict          # axis -> one-sentence str (backward-compat)
    axis_details: dict = field(default_factory=dict)   # axis -> AxisExplanation


def compute(activities: list[dict], gap_coverage_pct: float) -> CareerReadinessScore:
    if not activities:
        empty_detail = AxisExplanation(
            summary="No activities recorded yet.",
            contributing_factors=["Submit at least one activity to generate this score."],
            matched_evidence=[],
            missing_evidence=["Log activities describing real tasks you manage."],
            confidence=0.0,
        )
        return CareerReadinessScore(
            overall=0.0, technical=0.0, leadership=0.0,
            communication=0.0, consistency=0.0, growth=0.0,
            explanations={k: "No activities recorded yet." for k in _WEIGHTS},
            axis_details={k: empty_detail for k in _WEIGHTS},
        )

    technical,     td = _technical_score(gap_coverage_pct, activities)
    leadership,    ld = _leadership_score(activities)
    communication, cd = _communication_score(activities)
    consistency,   kd = _consistency_score(activities)
    growth,        gd = _growth_score(activities)

    overall = round(
        technical    * _WEIGHTS["technical"]
        + leadership * _WEIGHTS["leadership"]
        + communication * _WEIGHTS["communication"]
        + consistency * _WEIGHTS["consistency"]
        + growth      * _WEIGHTS["growth"],
        1,
    )

    return CareerReadinessScore(
        overall=overall,
        technical=technical,
        leadership=leadership,
        communication=communication,
        consistency=consistency,
        growth=growth,
        explanations={
            "technical":     td.summary,
            "leadership":    ld.summary,
            "communication": cd.summary,
            "consistency":   kd.summary,
            "growth":        gd.summary,
        },
        axis_details={
            "technical":     td,
            "leadership":    ld,
            "communication": cd,
            "consistency":   kd,
            "growth":        gd,
        },
    )


def _technical_score(gap_coverage_pct: float, activities: list[dict]):
    score = round(min(100.0, max(0.0, gap_coverage_pct)), 1)
    confidence = min(100.0, len(activities) * 8 + 20)

    matched = [
        f"Activity skill: \"{a.get('mapped_skill','')}\""
        for a in activities[:3] if a.get("mapped_skill")
    ]
    missing_hint = (
        "Upload a resume and log more role-specific activities to increase coverage."
        if gap_coverage_pct < 70 else
        "You're covering most required skills. Work on the remaining gaps in the learning plan."
    )
    detail = AxisExplanation(
        summary=f"{gap_coverage_pct:.0f}% of the target role's required skills are covered by your activities and resume.",
        contributing_factors=[
            f"Skill gap coverage: {gap_coverage_pct:.1f}% of role requirements matched.",
            f"Based on {len(activities)} logged activities.",
            "Includes both Gemini-identified skills and embedding-matched skills from your resume.",
        ],
        matched_evidence=matched,
        missing_evidence=[missing_hint],
        confidence=confidence,
    )
    return score, detail


def _leadership_score(activities: list[dict]):
    vals = [float(a.get("leadership_index") or 0) for a in activities]
    score = round(min(100.0, sum(vals) / max(len(vals), 1)), 1)
    confidence = min(100.0, len(activities) * 10)

    top3 = sorted(activities, key=lambda x: x.get("leadership_index", 0), reverse=True)[:3]
    matched = [
        f"\"{a.get('mapped_skill','')}\" — leadership index {a.get('leadership_index',0):.0f}"
        for a in top3 if a.get("mapped_skill")
    ]
    detail = AxisExplanation(
        summary=f"Average leadership index {score:.0f}/100 across {len(activities)} activities.",
        contributing_factors=[
            f"Average leadership_index: {score:.1f} (0–100 scale).",
            f"Highest single activity: {max(vals, default=0):.0f}.",
            f"Based on {len(activities)} activities with leadership scoring.",
            "Scores are computed by the AI hybrid pipeline (Gemini + embedding fusion).",
        ],
        matched_evidence=matched,
        missing_evidence=[
            "Log activities involving coordination, mentoring, or decision-making to raise this score."
        ] if score < 75 else ["Strong — continue documenting high-responsibility activities."],
        confidence=confidence,
    )
    return score, detail


def _communication_score(activities: list[dict]):
    scores = []
    strong_bullets = []
    weak_bullets   = []
    for a in activities:
        bullet = str(a.get("resume_snippet") or "").strip()
        if not bullet:
            scores.append(0.0)
            continue
        wc = len(bullet.split())
        s  = min(1.0, wc / 15.0)
        scores.append(s)
        if s >= 0.8:
            strong_bullets.append(f"\"{bullet[:80]}…\"" if len(bullet) > 80 else f"\"{bullet}\"")
        elif s < 0.5:
            weak_bullets.append(f"Too short ({wc} words): \"{bullet[:60]}\"")

    score      = round(sum(scores) / max(len(scores), 1) * 100, 1)
    confidence = min(100.0, len(activities) * 8)

    detail = AxisExplanation(
        summary=f"Communication score {score:.0f}/100 based on {len(activities)} resume bullet(s).",
        contributing_factors=[
            f"{len(strong_bullets)}/{len(activities)} bullets meet the 15-word quality threshold.",
            f"Average bullet word count: {sum(len(str(a.get('resume_snippet','')).split()) for a in activities)/max(len(activities),1):.0f} words (target: 15–20).",
            "Score rewards specific, detailed descriptions of your actions and their outcomes.",
        ],
        matched_evidence=strong_bullets[:2],
        missing_evidence=weak_bullets[:2] if weak_bullets else [
            "All bullets meet quality standards." if score >= 80 else
            "Describe your activities in more detail — include context, actions taken, and results."
        ],
        confidence=confidence,
    )
    return score, detail


def _consistency_score(activities: list[dict]):
    today = datetime.date.today()
    weeks_with_activity = set()
    week_details = []

    for a in activities:
        raw = str(a.get("created_at") or "")
        try:
            d = datetime.date.fromisoformat(raw[:10])
            weeks_ago = (today - d).days // 7
            if 0 <= weeks_ago < 12:
                weeks_with_activity.add(weeks_ago)
                week_details.append(f"Week -{weeks_ago}: \"{a.get('mapped_skill','activity')}\"")
        except (ValueError, TypeError):
            continue

    score      = round(len(weeks_with_activity) / 12 * 100, 1)
    confidence = min(100.0, len(activities) * 6 + 10)

    detail = AxisExplanation(
        summary=f"Active in {len(weeks_with_activity)}/12 recent weeks ({score:.0f}% consistency).",
        contributing_factors=[
            f"Logged activities in {len(weeks_with_activity)} of the last 12 calendar weeks.",
            "Each week with at least one activity contributes 8.3 points.",
            "Recruiter-facing metric: consistency signals professional growth discipline.",
        ],
        matched_evidence=week_details[:4],
        missing_evidence=[
            "Log at least one activity per week for the next 4 weeks to meaningfully improve this score."
        ] if score < 60 else ["Keep logging regularly to maintain this consistency score."],
        confidence=confidence,
    )
    return score, detail


def _growth_score(activities: list[dict]):
    if len(activities) < 2:
        detail = AxisExplanation(
            summary="Insufficient activity history to compute growth. Score defaulted to 50 (neutral).",
            contributing_factors=["Need at least 2 activities to detect a trend."],
            matched_evidence=[],
            missing_evidence=["Log more activities over time — growth is detected by comparing early vs. recent scores."],
            confidence=10.0,
        )
        return 50.0, detail

    scores  = [float(a.get("employability_score") or 0) for a in activities]
    earliest = sum(scores[-3:]) / min(3, len(scores))
    latest   = sum(scores[:3])  / min(3, len(scores))
    delta    = latest - earliest
    score    = round(min(100.0, max(0.0, 50 + (delta / 10.0) * 50)), 1)
    confidence = min(100.0, len(activities) * 7)

    direction = "improving" if delta > 1 else "declining" if delta < -1 else "stable"
    detail = AxisExplanation(
        summary=f"Employability score is {direction}: {earliest:.0f} (early) → {latest:.0f} (recent), Δ{delta:+.1f}.",
        contributing_factors=[
            f"Earliest 3 activities: avg employability {earliest:.1f}.",
            f"Most recent 3 activities: avg employability {latest:.1f}.",
            f"Delta: {delta:+.1f} points ({'positive growth' if delta > 0 else 'needs improvement'}).",
            "Score: +10 delta → 100, neutral → 50, -10 delta → 0.",
        ],
        matched_evidence=[
            f"Recent: \"{activities[0].get('mapped_skill','')}\" — score {activities[0].get('employability_score',0):.0f}"
        ] if activities else [],
        missing_evidence=[
            "Log more ambitious, higher-scope activities to raise your recent scores."
        ] if delta <= 0 else ["Keep logging high-impact activities to maintain upward growth."],
        confidence=confidence,
    )
    return score, detail

