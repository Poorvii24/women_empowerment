"""
services/ai_copilot.py
=======================
AI Career Copilot — a context-aware career mentor that answers questions
using only the user's own data: resume, logged activities, Career Readiness
score, ATS analysis, skill gap analysis, learning roadmap, target role, and
the opportunity engine's recommendations.

This module is intentionally the only place that knows how to build a
Copilot response — app.py's routes stay thin and just call `ask()`.

Architecture:
    ContextBuilder       -> build_user_context() / invalidate_context_cache()
    PromptBuilder         -> _build_prompt()
    ConversationManager   -> ConversationManager class (wraps db.py)
    ResponseFormatter     -> _format_gemini_response() / local fallback builders
    Public entry point    -> ask(user_id, message, gemini_client=None)

Performance (Task 11): build_user_context() reuses the exact same engines
already used by the Dashboard/Career Hub/Portfolio (scoring_engine,
ats_engine, skill_gap_engine, learning_recommender, opportunity_recommender)
— no new analysis logic is introduced. Results are cached per-user for a
short TTL so a back-and-forth conversation doesn't re-run the full analysis
pipeline on every single message.

Security (Task 12): the Gemini prompt explicitly instructs the model to
answer only from the supplied context and to say so plainly if something
isn't available, rather than inventing an answer. The local fallback (used
whenever Gemini isn't configured/available) is 100% rule-based against the
same context dict, so it can never fabricate information either.
"""

import json
import logging
import time

import db
from services import scoring_engine, ats_engine, skill_gap_engine, learning_recommender, opportunity_recommender

logger = logging.getLogger("isis.ai_copilot")

# ─────────────────────────── Context Builder ────────────────────────────────

_CONTEXT_CACHE = {}
_CONTEXT_TTL_SECONDS = 180  # short-lived cache: cheap to recompute, but avoids
# re-running the full analysis pipeline on every
# single message within one chat session


def _safe_call(fn, *args, default=None, label=""):
    try:
        return fn(*args)
    except Exception:
        logger.warning("ai_copilot_context_step_failed", extra={"step": label})
        return default


def _score_to_dict(score):
    if not score:
        return None
    return {
        "overall": round(score.overall, 1),
        "technical": round(score.technical, 1),
        "leadership": round(score.leadership, 1),
        "communication": round(score.communication, 1),
        "consistency": round(score.consistency, 1),
        "growth": round(score.growth, 1),
        "explanations": score.explanations,
    }


def _gap_to_dict(gap):
    if not gap:
        return None
    return {
        "coverage_pct": round(gap.coverage_pct, 1),
        "core_coverage_pct": round(gap.core_coverage_pct, 1),
        "matched": gap.matched[:10],
        "partial": gap.partial[:10],
        "missing": gap.missing[:10],
    }


def build_user_context(user_id):
    """
    Gathers everything the Copilot is allowed to reference about this user.
    Every value here is reused from existing engines — this function only
    orchestrates calls that already exist elsewhere in the app, wrapped
    defensively so one flaky step (e.g. the embedding model) never breaks
    the whole context.
    """
    cached = _CONTEXT_CACHE.get(user_id)
    if cached and (time.time() - cached["ts"]) < _CONTEXT_TTL_SECONDS:
        return cached["context"]

    target_role = db.get_user_target_role(user_id) or "Not set"
    activities = db.get_user_activities(user_id) or []
    resume = db.get_latest_resume(user_id)

    activity_skills = list({a.get("mapped_skill", "") for a in activities if a.get("mapped_skill")})
    resume_skills = resume["candidate_skills"] if resume else []
    all_skills = list(dict.fromkeys(activity_skills + resume_skills))
    resume_text = resume["raw_text"] if resume else ""

    gap = None
    if all_skills and target_role != "Not set":
        gap = _safe_call(skill_gap_engine.analyze_gap, target_role, all_skills, label="skill_gap")

    score = _safe_call(scoring_engine.compute, activities, gap.coverage_pct if gap else 0, label="scoring")

    ats = None
    if activities or resume_text:
        ats = _safe_call(ats_engine.compute_ats, target_role, all_skills, resume_text, activities, label="ats")

    recruiter = None
    if score and ats:
        recruiter = _safe_call(
            ats_engine.compute_recruiter_summary, target_role, score, ats, activities, resume_text, label="recruiter"
        )

    plan = None
    if gap and score:
        plan = _safe_call(
            learning_recommender.build_learning_plan,
            target_role,
            gap.missing,
            gap.partial,
            score,
            label="learning_plan",
        )

    opps = _safe_call(
        opportunity_recommender.get_opportunities,
        target_role,
        gap.missing if gap else [],
        label="opportunities",
        default={},
    )

    context = {
        "candidate_has_resume": resume is not None,
        "candidate_has_activities": bool(activities),
        "target_role": target_role,
        "activity_count": len(activities),
        "resume_skills": resume_skills[:30],
        "activity_skills": activity_skills[:30],
        "score": _score_to_dict(score),
        "ats": ats,
        "recruiter_summary": recruiter,
        "skill_gap": _gap_to_dict(gap),
        "learning_plan": plan,
        "opportunities": opps,
    }
    _CONTEXT_CACHE[user_id] = {"ts": time.time(), "context": context}
    return context


def invalidate_context_cache(user_id):
    """Force a fresh context on the next question rather than waiting out the
    TTL. Not required for correctness (the TTL already guarantees the
    Copilot is never more than a few minutes stale) but safe to call after a
    resume upload / new activity / target role change if ever wired in."""
    _CONTEXT_CACHE.pop(user_id, None)


# ─────────────────────────── Conversation Manager ───────────────────────────


class ConversationManager:
    """Thin wrapper around db.py's copilot_messages helpers."""

    def __init__(self, user_id):
        self.user_id = user_id

    def history(self, limit=20):
        return db.get_copilot_history(self.user_id, limit=limit)

    def append(self, role, content):
        db.insert_copilot_message(self.user_id, role, content)

    def clear(self):
        db.clear_copilot_history(self.user_id)


# ─────────────────────────── Prompt Builder ─────────────────────────────────

_SYSTEM_INSTRUCTIONS = """You are the ISIS Career Copilot — a warm, patient career mentor. You are NOT
a generic chatbot, and you are NOT a technical assistant. Many people you
talk to may have no resume, no formal education, low digital literacy, and
no familiarity with career or HR terminology — homemakers, farmers,
tailors, delivery partners, drivers, shop owners, caregivers, volunteers,
students, office workers, and freelancers all use this platform. Your job
is to help every one of them feel recognised and encouraged, never
confused, judged, or talked down to.

You must answer using ONLY the JSON "context" object provided to you below,
which contains this specific person's own resume skills, logged everyday
activities, readiness score, resume analysis, skill gap analysis, learning
roadmap, target role, and recommended opportunities.

How to talk:
- Use everyday words. Never say "ATS score" — say "resume quality" or "how
  well your resume comes across". Never say "confidence score" — say "how
  sure we are". Never say "skill gap" — say "skills you could learn next".
  Never say "career readiness" on its own without explaining what it means
  in plain terms ("how ready you are for the next step").
- If a technical or industry term is truly unavoidable, explain it in one
  simple clause right after using it, the way you'd explain it to a
  neighbour, not a colleague.
- Always ground your answer in this person's own data — their own words,
  their own activities, their own numbers. Reference specifics rather than
  generic advice.
- If the context doesn't contain what's needed to answer (no resume, no
  target role set yet), say so warmly and tell them exactly what simple
  step would help (e.g. "Once you tell us what kind of work you're hoping
  for, I can compare it against everything you've already shared with us.").
- Never invent skills, scores, or projects that aren't in the context.
- Never phrase anything as a deficiency or judgment. Instead of "you lack
  leadership" or "you scored low on X", say something like "We haven't
  found many examples of this yet — if you've organised people or events,
  tell us more so we can recognise that strength." Always leave room for the
  possibility that the evidence just hasn't been shared yet, not that the
  person lacks the quality.
- Celebrate what's already there before pointing toward what's next.
- When explaining a score or recommendation, weave in — only where truly
  useful, never forcing all of them into one short answer — what it means,
  why you noticed it, which of their own experiences led you there, how
  sure you are (in plain words, never a raw percentage), what a good next
  step looks like, and roughly how much effort it would take.
- When useful, ask a warm follow-up question to help narrow things down
  (e.g. if asked "how do I improve?", offer a few specific, friendly options).
- Keep responses short, warm, and encouraging — a few sentences, not an essay.

Respond ONLY with a JSON object matching this schema, no other text:
{
  "answer": "<main response, plain everyday language, markdown allowed>",
  "evidence": ["<short, specific point from their own activities/words>", ...] | [],
  "confidence": "High" | "Medium" | "Low" | null,
  "next_action": "<one small, concrete, encouraging next step>" | null,
  "expected_impact": "<short phrase, plain language>" | null,
  "estimated_effort": "<short phrase, e.g. 'about an afternoon'>" | null,
  "follow_up_questions": ["<short, warm question>", ...] | []
}
"""


def _build_prompt(context, history, message):
    history_lines = []
    for turn in history[-6:]:  # last 6 turns is plenty of conversational context
        role = "User" if turn["role"] == "user" else "Copilot"
        history_lines.append(f"{role}: {turn['content']}")
    history_block = "\n".join(history_lines) if history_lines else "(no prior messages)"

    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"CONTEXT (this user's real data):\n{json.dumps(context, default=str)}\n\n"
        f"CONVERSATION SO FAR:\n{history_block}\n\n"
        f"USER'S NEW QUESTION:\n{message}\n"
    )


# ─────────────────────────── Response Formatter ─────────────────────────────


def _format_gemini_response(raw_text):
    try:
        parsed = json.loads(raw_text)
    except Exception:
        return {
            "answer": raw_text.strip() or "I couldn't generate a response. Please try again.",
            "evidence": [],
            "confidence": None,
            "next_action": None,
            "expected_impact": None,
            "estimated_effort": None,
            "follow_up_questions": [],
        }
    return {
        "answer": str(parsed.get("answer", "")).strip() or "I couldn't generate a response. Please try again.",
        "evidence": parsed.get("evidence") or [],
        "confidence": parsed.get("confidence"),
        "next_action": parsed.get("next_action"),
        "expected_impact": parsed.get("expected_impact"),
        "estimated_effort": parsed.get("estimated_effort"),
        "follow_up_questions": parsed.get("follow_up_questions") or [],
    }


def _empty_response(answer, follow_up_questions=None):
    return {
        "answer": answer,
        "evidence": [],
        "confidence": None,
        "next_action": None,
        "expected_impact": None,
        "estimated_effort": None,
        "follow_up_questions": follow_up_questions or [],
    }


# ─────────────────────── Local (no-Gemini) fallback ─────────────────────────
# Fully rule-based against the same context dict Gemini would see — this can
# never fabricate information, only report what's actually in the context.


def _confidence_word(pct):
    if pct >= 75:
        return "quite sure"
    if pct >= 45:
        return "fairly sure"
    return "still learning about this"


def _tier_word(overall):
    if overall >= 75:
        return "in great shape"
    if overall >= 50:
        return "well on your way"
    return "just getting started"


def _local_fallback(context, message):
    q = message.lower()
    role = context["target_role"]
    score = context["score"]
    ats = context["ats"]
    gap = context["skill_gap"]
    plan = context["learning_plan"]
    opps = context["opportunities"] or {}
    recruiter = context["recruiter_summary"]

    def missing_target_role():
        return _empty_response(
            "You haven't told us what role you're hoping for yet, so I can't compare your experience "
            "against it. Head to the Career Hub and tell us — I'll be able to give you much more "
            "specific, useful guidance after that.",
            follow_up_questions=["What kind of work are you hoping to do?"],
        )

    if not score:
        return _empty_response(
            "I don't have much to go on yet — tell us about a few things you've done recently, and "
            "I'll be able to help."
        )

    if "interview" in q:
        return {
            "answer": (
                f"You're {_confidence_word(ats['interview_ready'])} ready for interview conversations right now."
                if ats
                else "I don't have enough to tell you about interview readiness just yet."
            ),
            "evidence": [],
            "confidence": "Medium" if ats else None,
            "next_action": "Try explaining 2-3 things you're proud of out loud, focusing on what you actually did and why it mattered.",
            "expected_impact": None,
            "estimated_effort": None,
            "follow_up_questions": [],
        }

    if "readiness" in q or "career readiness" in q:
        return {
            "answer": f"You're {_tier_word(score['overall'])} — {score['overall']:.0f} out of 100 on how ready you "
            f"are for your next opportunity. This looks at five things: your skills and know-how "
            f"({score['technical']:.0f}), how you lead others ({score['leadership']:.0f}), how clearly "
            f"you explain things ({score['communication']:.0f}), how consistently you've been showing "
            f"up ({score['consistency']:.0f}), and how you're growing over time ({score['growth']:.0f}).",
            "evidence": [f"{k.title()}: {v:.0f}" for k, v in score.items() if k not in ("overall", "explanations")],
            "confidence": "High",
            "next_action": "Let's look at whichever of these feels lowest to you — that's usually the fastest place to grow.",
            "expected_impact": None,
            "estimated_effort": None,
            "follow_up_questions": ["Which one should I focus on?", "How can I get even more ready?"],
        }

    if "ats" in q or "resume quality" in q:
        if not ats:
            return _empty_response(
                "I don't have anything to tell you about your resume yet — add one, or tell us about a "
                "few things you've done, and I'll take a look."
            )
        return {
            "answer": f"Your resume comes across {_confidence_word(ats['ats_score']).replace('sure', 'strongly')} "
            f"to hiring systems, and you're {_tier_word(ats['interview_ready'])} for interviews.",
            "evidence": [
                (
                    f"A few words worth adding: {', '.join(ats.get('missing_keywords', [])[:5])}"
                    if ats.get("missing_keywords")
                    else "You're already covering the important words well."
                )
            ],
            "confidence": "Medium",
            "next_action": "Try weaving those words naturally into how you describe what you've done.",
            "expected_impact": "Your resume gets noticed more often",
            "estimated_effort": "About 30-60 minutes",
            "follow_up_questions": [],
        }

    if "missing" in q and "skill" in q:
        if not gap:
            return missing_target_role()
        missing = [m["skill"] for m in gap["missing"]]
        if not missing:
            return {
                "answer": f"You're already covering everything important for {role} — nothing missing that I can see!",
                "evidence": [],
                "confidence": "High",
                "next_action": None,
                "expected_impact": None,
                "estimated_effort": None,
                "follow_up_questions": [],
            }
        return {
            "answer": f"Here are some skills worth learning next for {role}: " + ", ".join(missing[:8]) + ".",
            "evidence": missing[:8],
            "confidence": "High",
            "next_action": f"A good place to start would be {missing[0]}." if missing else None,
            "expected_impact": "Matches you better with this kind of work",
            "estimated_effort": None,
            "follow_up_questions": [],
        }

    if "project" in q:
        projects = opps.get("projects") or []
        if not projects:
            return _empty_response(
                "I don't have anything to suggest yet — tell us what role you're hoping for and I'll find some ideas."
            )
        top = projects[0]
        return {
            "answer": f"You could try **{top.get('title')}** next. {top.get('description', '')}",
            "evidence": [f"How challenging: {top.get('difficulty', 'Not sure yet')}"],
            "confidence": "Medium",
            "next_action": f"Give {top.get('title')} a try",
            "expected_impact": "Gives you something concrete to show others",
            "estimated_effort": None,
            "follow_up_questions": [p.get("title") for p in projects[1:3]],
        }

    if "certif" in q:
        certs = opps.get("certifications") or []
        if not certs:
            return _empty_response(
                "I don't have any course suggestions yet — tell us what role you're hoping for and I'll find some."
            )
        top = certs[0]
        return {
            "answer": f"**{top.get('title')}** (from {top.get('provider', 'a trusted provider')}) could be worth a look.",
            "evidence": [f"Cost: {top.get('cost', 'Not sure yet')}"],
            "confidence": "Medium",
            "next_action": f"Look into {top.get('title')}",
            "expected_impact": None,
            "estimated_effort": None,
            "follow_up_questions": [],
        }

    if "ready" in q and role.lower() in q:
        if not gap:
            return missing_target_role()
        verdict = recruiter["overall_tier"] if recruiter else None
        verdict_word = {"Strong": "in great shape", "Developing": "well on your way", "Needs Work": "just getting started"}.get(
            verdict, _tier_word(score["overall"])
        )
        return {
            "answer": f"Based on everything you've shared, you're **{verdict_word}** for {role} — about "
            f"{gap['coverage_pct']:.0f}% of what's usually asked for already matches what you've done.",
            "evidence": [f"How ready overall: {score['overall']:.0f}/100", f"How well you match: {gap['coverage_pct']:.0f}%"],
            "confidence": "Medium",
            "next_action": recruiter["next_action"] if recruiter else None,
            "expected_impact": None,
            "estimated_effort": None,
            "follow_up_questions": [],
        }

    if "roadmap" in q or "plan" in q:
        if not plan:
            return missing_target_role()
        d30 = plan.get("day_30") or []
        return {
            "answer": "A good place to start would be: "
            + (d30[0]["skill"] if d30 else "sharing a few more things you've done, so we can build your plan."),
            "evidence": [it.get("skill", "") for it in d30[:3]],
            "confidence": "Medium",
            "next_action": d30[0]["skill"] if d30 else None,
            "expected_impact": None,
            "estimated_effort": None,
            "follow_up_questions": ["What comes after that?"],
        }

    if "improve" in q and len(q.split()) < 8:
        return _empty_response(
            "I'd love to help you grow — what would you like to focus on?",
            follow_up_questions=[
                "How my resume comes across",
                "Skills and know-how",
                "Getting ready for interviews",
                "Leading others",
                "Explaining things clearly",
            ],
        )

    # Generic fallback — still grounded in real data, never invented
    return {
        "answer": f"Here's where things stand: you're {_tier_word(score['overall'])} ({score['overall']:.0f} out of 100)"
        + (f", working toward {role}." if role != "Not set" else ". You haven't told us what role you're hoping for yet."),
        "evidence": [],
        "confidence": "Medium",
        "next_action": None,
        "expected_impact": None,
        "estimated_effort": None,
        "follow_up_questions": [
            "What does my readiness score mean?",
            "What skills could I learn next?",
            "What should I try next?",
        ],
    }


# ─────────────────────────── Public entry point ─────────────────────────────


def ask(user_id, message, gemini_client=None):
    """
    The single entry point Flask routes call. Builds context, builds the
    prompt, calls Gemini if a configured client was supplied, otherwise
    falls back to the fully local rule-based responder — either way the
    response is grounded only in the user's own data, persisted to the
    conversation history, and returned in the same normalized shape.
    """
    if not message or not message.strip():
        return _empty_response("Ask me anything about your career readiness, skills, projects, or roadmap!")

    convo = ConversationManager(user_id)
    context = build_user_context(user_id)
    history = convo.history()

    result = None
    used_gemini = False
    if gemini_client is not None:
        try:
            from google.genai import types

            prompt = _build_prompt(context, history, message)
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            result = _format_gemini_response(response.text)
            used_gemini = True
        except Exception as e:
            logger.warning(
                "ai_copilot_gemini_call_failed", extra={"error_type": type(e).__name__, "error_message": str(e)}
            )
            result = None

    if result is None:
        result = _local_fallback(context, message)

    result["source"] = "gemini" if used_gemini else "local"

    convo.append("user", message)
    convo.append("assistant", result["answer"])

    return result
