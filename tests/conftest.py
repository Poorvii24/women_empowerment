"""
tests/conftest.py
==================
Shared pytest fixtures for the whole test suite (Task 11).

Key design decisions:
  - Every test runs against an isolated temp SQLite file (db.DB_PATH is
    monkeypatched before db.init_db() runs), never the real
    isis_portfolio.db — so running the test suite can never corrupt or
    pollute the demo/seed data.
  - skill_gap_engine.analyze_gap is faked by default (see `fake_skill_gap`,
    autouse) so the test suite never depends on network access to
    huggingface.co, consistent with the existing pattern in
    tests/test_nlp_pipeline.py (which fakes at the embedding layer instead —
    both approaches coexist; this one is simpler for route/integration
    tests that only care about response shape, not matching semantics).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import tempfile
import pytest

import db


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Points db.DB_PATH at a fresh temp SQLite file for the duration of one test."""
    db_file = tmp_path / "test_isis.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    db.init_db()
    return db_file


@pytest.fixture()
def app_module(test_db, monkeypatch):
    """Imports app.py fresh against the isolated test_db, disabling rate
    limiting so repeated test requests never trip it."""
    monkeypatch.setenv("ISIS_ENV", "testing")
    import importlib
    import app as appmod

    importlib.reload(appmod)
    appmod.db.DB_PATH = str(test_db)
    appmod.app.config["TESTING"] = True
    appmod.app.config["WTF_CSRF_ENABLED"] = True  # keep CSRF on; tests fetch a real token
    try:
        appmod.limiter.enabled = False
    except Exception:
        pass
    return appmod


@pytest.fixture()
def test_user(app_module):
    """Creates one throwaway user directly via the repository layer."""
    from werkzeug.security import generate_password_hash

    user_id = app_module.user_repository.create("testuser", generate_password_hash("Sup3rSecret!"))
    return {"id": user_id, "username": "testuser"}


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture()
def auth_client(app_module, client, test_user):
    """A Flask test client with an authenticated session for `test_user`."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(test_user["id"])
        sess["_fresh"] = True
    return client


@pytest.fixture()
def csrf_token(auth_client):
    """Fetches a real CSRF token the same way the frontend does — from the
    meta tag on any authenticated page — so POST tests exercise real CSRF
    validation instead of bypassing it."""
    resp = auth_client.get("/career")
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    assert match, "csrf-token meta tag not found on /career — did the page fail to render?"
    return match.group(1)


@pytest.fixture(autouse=True)
def fake_skill_gap(monkeypatch):
    """Replaces the embedding-model-backed skill_gap_engine.analyze_gap with
    a deterministic fake for every test, so the suite never depends on
    network access to huggingface.co. Tests that specifically want to
    exercise the real embedding pipeline should use
    tests/test_nlp_pipeline.py's set_encoder_override pattern instead."""
    from services.skill_gap_engine import SkillGapResult
    import services.skill_gap_engine as sge

    def _fake(role, skills):
        return SkillGapResult(
            role=role,
            matched=[{"skill": "Communication", "similarity": 0.8, "matched_by": "General Administrative Support"}],
            partial=[],
            missing=[{"skill": "SQL", "tier": "core"}, {"skill": "A/B Testing", "tier": "core"}],
            coverage_pct=40.0,
            core_coverage_pct=30.0,
            user_skill_count=len(skills),
        )

    monkeypatch.setattr(sge, "analyze_gap", _fake)
    yield
