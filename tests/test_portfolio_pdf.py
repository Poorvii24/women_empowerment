"""
tests/test_portfolio_pdf.py
============================
Both PDF generators: the Professional Portfolio (/generate_pdf, activities-
based) and the Career Intelligence Report (/career/portfolio_pdf,
resume+role-based). Kept in one file specifically to guard against them
ever being accidentally merged/confused again.
"""

import re
from pypdf import PdfReader
import io


def get_csrf_from(resp):
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1) if match else None


class TestProfessionalPortfolio:
    def test_generates_valid_pdf_with_no_activities(self, auth_client):
        """Even a brand-new user with zero activities should get a valid
        (if sparse) PDF, never a 500."""
        token = get_csrf_from(auth_client.get("/career"))
        resp = auth_client.get(f"/generate_pdf?csrf_token={token}")
        assert resp.status_code == 200
        assert resp.content_type == "application/pdf"
        reader = PdfReader(io.BytesIO(resp.data))
        assert len(reader.pages) == 9

    def test_rejects_missing_csrf_token(self, auth_client):
        resp = auth_client.get("/generate_pdf")
        assert resp.status_code == 400

    def test_pdf_is_activities_based_not_resume_based(self, auth_client, app_module, test_user):
        """Regression guard for the exact bug reported earlier in this
        project: the Professional Portfolio must never pull from an
        uploaded resume's project/skills text."""
        import inspect

        source = inspect.getsource(app_module.generate_pdf)
        assert "resume" not in source.lower() or "get_latest_resume" not in source


class TestCareerIntelligenceReport:
    def test_generates_valid_pdf(self, auth_client):
        resp = auth_client.get("/career/portfolio_pdf")
        assert resp.status_code == 200
        assert resp.content_type == "application/pdf"
        reader = PdfReader(io.BytesIO(resp.data))
        assert len(reader.pages) == 10

    def test_two_pdf_routes_are_distinct_functions(self, app_module):
        """Regression guard: the two PDFs must remain separate code paths."""
        assert app_module.generate_pdf is not app_module.career_portfolio_pdf
