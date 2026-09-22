"""
tests/test_copilot_language.py
================================
Locks in the plain-language, encouraging tone of the AI Copilot's local
fallback responder (the UX/accessibility pass) — no raw jargon, no
percentage-only confidence, never phrased as a deficiency.
"""

from services import ai_copilot


class TestConfidenceWord:
    def test_high_confidence_is_plain_language(self):
        assert ai_copilot._confidence_word(90) == "quite sure"

    def test_medium_confidence_is_plain_language(self):
        assert ai_copilot._confidence_word(50) == "fairly sure"

    def test_low_confidence_is_encouraging_not_judgmental(self):
        result = ai_copilot._confidence_word(10)
        assert "lack" not in result.lower()
        assert "poor" not in result.lower()
        assert "learning" in result.lower()


class TestTierWord:
    def test_high_score_is_encouraging(self):
        assert ai_copilot._tier_word(90) == "in great shape"

    def test_low_score_is_never_phrased_as_deficiency(self):
        result = ai_copilot._tier_word(10)
        assert "lack" not in result.lower()
        assert "poor" not in result.lower()
        assert "bad" not in result.lower()
        assert "started" in result.lower()


class TestLocalFallbackTone:
    """Spot-checks that the local fallback (what most users see, since
    Gemini is often unconfigured) never leaks raw ML/HR jargon."""

    JARGON_TERMS = ["ats score", "confidence score", "skill gap", "similarity"]

    def _context(self, **overrides):
        base = {
            "target_role": "Not set",
            "score": None,
            "ats": None,
            "skill_gap": None,
            "learning_plan": None,
            "opportunities": {},
            "recruiter_summary": None,
        }
        base.update(overrides)
        return base

    def test_missing_target_role_message_has_no_jargon(self):
        ctx = self._context()
        result = ai_copilot._local_fallback(ctx, "which skills am I missing?")
        low = result["answer"].lower()
        for term in self.JARGON_TERMS:
            assert term not in low

    def test_readiness_answer_has_no_raw_jargon_terms(self):
        ctx = self._context(
            score={
                "overall": 62,
                "technical": 55,
                "leadership": 70,
                "communication": 60,
                "consistency": 58,
                "growth": 65,
                "explanations": {},
            }
        )
        result = ai_copilot._local_fallback(ctx, "explain my career readiness")
        low = result["answer"].lower()
        for term in self.JARGON_TERMS:
            assert term not in low
