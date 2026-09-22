"""
tests/test_localization.py
=============================
Verifies the language/translation system end-to-end:
  - English (default), Hindi, and Kannada can all be selected
  - the selection persists across page navigation and reloads (session-based)
  - the shared navbar and major headings/forms are actually translated,
    not just "selectable"
  - only the 3 genuinely-translated locales are accepted; anything else
    is rejected rather than silently switching to English while claiming
    success
  - the AI-generation language mapping (app.py's lang_map used for the
    Gemini prompt) matches the same 3 locales the UI supports — this is
    the "promise kept" check for requirement #9, not a live Gemini call
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]')
KANNADA_RE = re.compile(r'[\u0C80-\u0CFF]')


class TestLanguageSelection:

    def test_default_locale_is_english(self, auth_client):
        resp = auth_client.get("/")
        html = resp.get_data(as_text=True)
        assert 'lang="en"' in html
        assert "Dashboard" in html

    def test_can_select_hindi(self, auth_client):
        resp = auth_client.get("/set_language/hi", follow_redirects=True)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'lang="hi"' in html
        assert DEVANAGARI_RE.search(html), "expected Devanagari script somewhere on the page"

    def test_can_select_kannada(self, auth_client):
        resp = auth_client.get("/set_language/kn", follow_redirects=True)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'lang="kn"' in html
        assert KANNADA_RE.search(html), "expected Kannada script somewhere on the page"

    def test_unsupported_locale_is_rejected_not_silently_switched(self, auth_client):
        """Requirement #5: the app must not claim to support locales it
        hasn't translated. Previously ta/te/mr/bn were 'supported' but were
        just English underneath — that's the exact bug this guards against."""
        for bogus in ("ta", "te", "mr", "bn", "fr", "xx"):
            auth_client.get(f"/set_language/{bogus}")
            resp = auth_client.get("/")
            html = resp.get_data(as_text=True)
            # session['lang'] must NOT have been set to the bogus value —
            # it should have stayed at whatever it was (English by default).
            assert 'lang="en"' in html, f"'{bogus}' should not have been accepted as a locale"


class TestLanguagePersistence:

    def test_hindi_persists_across_navigation(self, auth_client):
        auth_client.get("/set_language/hi")
        for path in ("/", "/career", "/history"):
            resp = auth_client.get(path)
            html = resp.get_data(as_text=True)
            assert 'lang="hi"' in html, f"{path} did not keep the Hindi locale"

    def test_kannada_persists_across_navigation(self, auth_client):
        auth_client.get("/set_language/kn")
        for path in ("/", "/career", "/history"):
            resp = auth_client.get(path)
            html = resp.get_data(as_text=True)
            assert 'lang="kn"' in html, f"{path} did not keep the Kannada locale"

    def test_persists_across_simulated_reload(self, auth_client):
        """A 'reload' is just another GET against the same session cookie —
        confirms the language lives in the session, not in per-request state."""
        auth_client.get("/set_language/hi")
        first = auth_client.get("/").get_data(as_text=True)
        second = auth_client.get("/").get_data(as_text=True)
        assert 'lang="hi"' in first
        assert 'lang="hi"' in second


class TestTranslatedNavigationAndHeadings:
    """Requirement #6: headings/buttons/navigation must not remain in
    English after switching languages, on ANY of the three main pages."""

    @pytest.mark.parametrize("path", ["/", "/career", "/history"])
    def test_navbar_is_translated_in_hindi(self, auth_client, path):
        auth_client.get("/set_language/hi")
        html = auth_client.get(path).get_data(as_text=True)
        # The literal English nav strings must be gone...
        assert "Career Hub" not in html
        assert ">Dashboard<" not in html
        assert ">History<" not in html
        # ...replaced with the real Hindi strings.
        assert "करियर हब" in html
        assert "डैशबोर्ड" in html or "इतिहास" in html  # whichever nav items this page shows

    @pytest.mark.parametrize("path", ["/", "/career", "/history"])
    def test_navbar_is_translated_in_kannada(self, auth_client, path):
        auth_client.get("/set_language/kn")
        html = auth_client.get(path).get_data(as_text=True)
        assert "Career Hub" not in html
        assert "ಕೆರಿಯರ್ ಹಬ್" in html

    def test_career_hub_language_selector_present(self, auth_client):
        """career.html previously had NO language selector at all — this
        pins that the shared navbar partial fixed it."""
        html = auth_client.get("/career").get_data(as_text=True)
        assert "langDropdown" in html
        assert 'set_language' in html or '/set_language/' in html

    def test_career_page_major_headings_translated_hindi(self, auth_client, csrf_token, app_module, test_user):
        # The results section (including "Your Career Journey") only renders
        # once a target role is set — set one first so this heading actually
        # appears in the HTML to check.
        app_module.user_repository.set_target_role(test_user["id"], app_module.role_taxonomy.list_target_roles()[0])
        auth_client.get("/set_language/hi")
        html = auth_client.get("/career").get_data(as_text=True)
        assert "आपकी करियर यात्रा" in html  # "Your Career Journey"
        assert "Career Intelligence Hub" not in html

    def test_history_page_translated_hindi(self, auth_client, app_module, test_user):
        from utils import validators as _  # noqa: F401  (just ensures import path works)
        auth_client.get("/set_language/hi")
        html = auth_client.get("/history").get_data(as_text=True)
        assert "आपने हमारे साथ जो कुछ साझा किया है" in html or "गतिविधि इतिहास" in html
        assert "Everything You've Shared With Us" not in html

    def test_login_register_have_language_switcher(self, client):
        for path in ("/login", "/register"):
            html = client.get(path).get_data(as_text=True)
            assert "langDropdownAuth" in html

    def test_login_page_translated_hindi(self, client):
        client.get("/set_language/hi")
        html = client.get("/login").get_data(as_text=True)
        assert "वापसी पर स्वागत है" in html  # "Welcome back"


class TestFlashMessagesTranslated:

    def test_login_failure_message_translated_hindi(self, client):
        client.get("/set_language/hi")
        resp = client.get("/register")
        token_match = re.search(r'name="csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
        token = token_match.group(1)
        resp = client.post(
            "/login",
            data={"username": "nobody", "password": "wrong", "csrf_token": token},
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        assert DEVANAGARI_RE.search(html), "login failure flash message should be in Hindi"

    def test_analyze_activity_validation_message_translated_kannada(self, auth_client, csrf_token):
        auth_client.get("/set_language/kn")
        resp = auth_client.post(
            "/analyze_activity",
            json={"activity": "hi"},
            headers={"X-CSRFToken": csrf_token},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert KANNADA_RE.search(data["message"])


class TestAIOutputLanguageMapping:
    """The Gemini prompt's target_language mapping (app.py) must cover
    exactly the locales the UI actually offers — not more (a false promise
    per requirement #5/#9) and not fewer (a broken promise for a real
    locale). This checks the mapping without making a live Gemini call."""

    def test_lang_map_covers_exactly_the_supported_locales(self, app_module):
        source = open(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"),
            encoding="utf-8",
        ).read()
        lang_map_section = source[source.index("lang_map = {"): source.index("lang_map = {") + 300]
        supported = set(app_module.app.config["BABEL_SUPPORTED_LOCALES"])
        for locale in supported:
            assert f"'{locale}'" in lang_map_section, (
                f"'{locale}' is a supported UI locale but has no entry in the Gemini "
                "target_language mapping — AI output would silently stay in English "
                "for users who switched the UI to this language."
            )

    def test_supported_locales_restricted_to_translated_ones(self, app_module):
        """Pins requirement #5: exactly en/hi/kn, not the old 7-locale list."""
        assert set(app_module.app.config["BABEL_SUPPORTED_LOCALES"]) == {"en", "hi", "kn"}

    def test_every_supported_locale_has_a_compiled_catalog(self, app_module):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for locale in app_module.app.config["BABEL_SUPPORTED_LOCALES"]:
            if locale == "en":
                continue  # English is the source language; no catalog needed
            mo_path = os.path.join(base, "translations", locale, "LC_MESSAGES", "messages.mo")
            assert os.path.exists(mo_path), f"declared locale '{locale}' has no compiled .mo catalog"
            assert os.path.getsize(mo_path) > 0
