"""
services/growth_tracker.py
============================
Aggregates historical activity data for dashboard visualisation.

Produces three chart-ready datasets:
  weekly_activity    – activity count per calendar week (last 12 weeks)
                       → used for the "Activity Heatmap" / bar chart
  skill_trend        – average employability_score per week (last 12 weeks)
                       → used for the "Skill Growth" line chart
  skill_distribution – count of activities per leadership_category
                       → used for the "Skill Distribution" donut chart

All return-value date labels are ISO-format week start dates (Monday),
so the frontend can sort and display them without parsing.
"""
import datetime
import logging
from collections import defaultdict

logger = logging.getLogger("isis.services.growth_tracker")

_WEEKS_LOOKBACK = 12


def _week_start(d: datetime.date) -> str:
    """Return the ISO date string for the Monday of the week containing `d`."""
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def _parse_date(raw: str) -> datetime.date | None:
    """Parse ISO-ish SQLite date string, return None on failure."""
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def compute_growth_data(activities: list[dict]) -> dict:
    """
    Main entry point. Takes the raw activity list from db.get_user_activities()
    and returns three chart-ready datasets.
    """
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(weeks=_WEEKS_LOOKBACK)

    weekly_counts: dict[str, int] = defaultdict(int)
    weekly_scores: dict[str, list[float]] = defaultdict(list)
    skill_dist: dict[str, int] = defaultdict(int)

    for a in activities:
        d = _parse_date(a.get("created_at"))
        if d and d >= cutoff:
            w = _week_start(d)
            weekly_counts[w] += 1
            score = a.get("employability_score")
            if score is not None:
                weekly_scores[w].append(float(score))

        cat = a.get("leadership_category") or "Other"
        skill_dist[cat] += 1

    # Build a complete 12-week series even for weeks with no activity
    all_weeks = [
        _week_start(today - datetime.timedelta(weeks=i))
        for i in range(_WEEKS_LOOKBACK - 1, -1, -1)
    ]

    weekly_activity = [
        {"week": w, "count": weekly_counts.get(w, 0)}
        for w in all_weeks
    ]

    weekly_skill_trend = [
        {
            "week": w,
            "avg_score": round(
                sum(weekly_scores[w]) / len(weekly_scores[w]), 1
            ) if weekly_scores.get(w) else None,
        }
        for w in all_weeks
    ]

    skill_distribution = [
        {"category": cat, "count": count}
        for cat, count in sorted(skill_dist.items(), key=lambda x: -x[1])
    ]

    # Monthly progress summary (last 3 months)
    monthly_progress = _monthly_summary(activities, today)

    return {
        "weekly_activity": weekly_activity,
        "weekly_skill_trend": weekly_skill_trend,
        "skill_distribution": skill_distribution,
        "monthly_progress": monthly_progress,
        "total_activities": len(activities),
        "weeks_active": sum(1 for w in all_weeks if weekly_counts.get(w, 0) > 0),
    }


def _monthly_summary(activities: list[dict], today: datetime.date) -> list[dict]:
    """Returns one entry per calendar month for the last 3 months."""
    months = {}
    for i in range(2, -1, -1):
        month_start = (today.replace(day=1) - datetime.timedelta(days=i * 28)).replace(day=1)
        key = month_start.strftime("%b %Y")
        months[key] = {"month": key, "count": 0, "avg_score": [], "date": month_start}

    for a in activities:
        d = _parse_date(a.get("created_at"))
        if not d:
            continue
        key = d.replace(day=1).strftime("%b %Y")
        if key in months:
            months[key]["count"] += 1
            score = a.get("employability_score")
            if score is not None:
                months[key]["avg_score"].append(float(score))

    result = []
    for entry in sorted(months.values(), key=lambda x: x["date"]):
        scores = entry["avg_score"]
        result.append({
            "month": entry["month"],
            "count": entry["count"],
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        })
    return result
