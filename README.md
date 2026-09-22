# ISIS — Invisible Skill Intelligence System

An AI-powered career intelligence platform that translates real-world,
everyday activities (organizing an event, managing a budget, coordinating
volunteers) into recognized, quantified professional skills — alongside
resume-based skill-gap analysis against a target role, an AI Career
Copilot mentor, and two distinct PDF exports.

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture Overview](#architecture-overview)
- [Folder Structure](#folder-structure)
- [Environment Variables](#environment-variables)
- [Running Tests](#running-tests)
- [Docker Deployment](#docker-deployment)
- [API Reference](#api-reference)
- [Developer Guide](#developer-guide)
- [Further Reading](#further-reading)

## Quick Start

### Local (no Docker)

```bash
git clone <repo-url> && cd women_empowerment
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

python -m nltk.downloader punkt_tab averaged_perceptron_tagger_eng stopwords wordnet omw-1.4
# ^ one-time download for the classical NLP pipeline (tokenization, POS
# tagging, lemmatization). If this machine has no network access at deploy
# time, the app still runs — nlp/text_pipeline.py falls back to a
# regex-based tokenizer automatically instead of crashing.

cp .env.example .env
# Edit .env — at minimum leave ISIS_ENV=development for local use.
# Optional: add GEMINI_API_KEY for AI-powered analysis/Copilot responses
# (both features work without it, via a local fallback).

python scripts/seed_db.py   # optional: creates a demo user with sample data
python app.py
# -> http://127.0.0.1:5000
```

### Docker

```bash
cp .env.example .env
echo "ISIS_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
docker compose up -d
# -> http://localhost:5000
docker compose exec isis python scripts/seed_db.py   # optional demo data
```

See [Docker Deployment](#docker-deployment) below for the development profile
and other options.

## Architecture Overview

```
Browser (index.html / career.html / history.html)
        │  fetch() + session cookie + CSRF token
        ▼
┌─────────────────────────────────────────────────────────────┐
│ app.py — Flask routes (thin: auth, validation, delegate)     │
├─────────────────────────────────────────────────────────────┤
│ repositories/   →  thin wrappers around db.py                │
│ services/       →  business logic (scoring, ATS, skill gap,   │
│                     learning roadmap, opportunities, PDF      │
│                     design system, AI Copilot)                │
│ utils/          →  validators, standardized API responses     │
├─────────────────────────────────────────────────────────────┤
│ db.py — SQLite persistence (single source of truth for SQL)   │
└─────────────────────────────────────────────────────────────┘
        │
        ├──► nlp/  (hybrid NLP pipeline: tokenization, lemmatization, POS
        │           tagging, keyphrase extraction, TF-IDF features,
        │           sentence-transformer embeddings, skill matching)
        └──► google-genai (Gemini)   ──► optional; both AI features degrade
                                          gracefully to local logic without it
```

**NLP pipeline** (`/analyze_activity`, see `nlp/__init__.py` for the full
module map): raw text → `preprocessing.clean_text()` → `text_pipeline`
(tokenize → stopword removal → POS tag → lemmatize) → `text_pipeline
.extract_noun_phrases()` (keyphrase candidates) → `keyphrase_extractor`
(TF-IDF-ranked keyphrases) + `feature_representation` (TF-IDF cosine
similarity) blended with `embedding_engine` (sentence-transformer cosine
similarity) → `skill_matcher.analyze_activity_semantic()` → career mapping
in `app.py` / `services/role_taxonomy.py`. Gemini enriches the narrative
output (titles, bullets, opportunities) when configured; every numeric
score is grounded against the local hybrid engine either way, and the
whole local pipeline runs even if Gemini is unset or its call fails.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed diagrams
(request flow, AI pipeline, database ERD, deployment topology) and the
reasoning behind several scope decisions made during the production-
readiness pass.

### The two PDFs (deliberately separate)

| | `/generate_pdf` | `/career/portfolio_pdf` |
|---|---|---|
| Name | Professional Portfolio | Career Intelligence Report |
| Data source | **Logged activities only** | Resume + target role |
| Purpose | "Here's what you've actually done" | "Here's how you match a target role" |
| Pages | 9 | 10 |

These were accidentally conflated once during development (see git history /
project retrospective) — `tests/test_portfolio_pdf.py` now guards against
that regression happening again.

## Folder Structure

```
app.py                   Flask routes (thin — delegates to services/repositories)
config.py                Environment-based configuration (dev/testing/production)
db.py                     SQLite persistence — the single source of truth for SQL
repositories/             Class-based wrappers around db.py (Task 3 pattern)
services/                 Business logic — scoring, ATS, skill gap, learning
                          roadmap, opportunities, PDF design system, AI Copilot
utils/                    validators.py, responses.py — shared helpers
nlp/                      Hybrid NLP pipeline: classical (tokenization, POS
                          tagging, lemmatization, TF-IDF, keyphrase
                          extraction) + embedding-based (sentence-transformers)
                          skill matching
scripts/                  seed_db.py, backup_db.py
tests/                    pytest suite (conftest.py has all shared fixtures)
docs/                     openapi.yaml, ARCHITECTURE.md, DEPLOYMENT.md, AUDIT.md
.github/workflows/        CI pipeline
Dockerfile, docker-compose.yml
*.html, script.js, copilot_widget.js, styles.css   Frontend (server-rendered
                          Jinja templates + vanilla JS, no build step)
```

## Environment Variables

See [.env.example](.env.example) for the full list with defaults and
explanations. Nothing is hardcoded — every secret and environment-specific
value is read from the environment, with sensible development-only defaults
where safe to have them.

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
pytest tests/ --cov=app --cov=db --cov=services --cov=repositories --cov=utils --cov=config --cov-report=term-missing
```

Every test runs against an isolated temporary SQLite database (see
`tests/conftest.py`) — the real `isis_portfolio.db` is never touched by the
test suite. Tests that would otherwise depend on the embedding model
(huggingface.co) use a deterministic fake instead (see
`conftest.py::fake_skill_gap`, or `tests/test_nlp_pipeline.py`'s
`set_encoder_override` for lower-level NLP pipeline tests).

## Docker Deployment

```bash
# Production (gunicorn, per Dockerfile)
docker compose up -d

# Development (Flask dev server, live-reloading source mount)
docker compose --profile dev up
```

Both persist the SQLite database and log files in named Docker volumes so
data survives container rebuilds. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for backup/restore, scaling notes,
and the reasoning behind sticking with SQLite + gunicorn rather than a full
Postgres migration in this pass.

## API Reference

- Interactive Swagger UI: `/api/docs` (once the app is running)
- Raw spec: `/api/openapi.yaml`, or the source at
  [docs/openapi.yaml](docs/openapi.yaml)

## Developer Guide

- **Adding a new route**: keep it thin — parse/validate input (see
  `utils/validators.py`), delegate to a repository or service, return via
  `utils/responses.py`'s helpers (or the existing `{"status": ..., ...}`
  shape other routes already use).
- **Adding a new repository**: wrap the relevant `db.py` functions; don't
  reimplement SQL in the repository layer.
- **Adding a new service**: pure business logic, no Flask imports.
- **PDF design system**: `services/pdf_design.py` — reusable fpdf2
  components (cards, KPI grids, timelines, charts). Both PDF routes use it.
- **Formatting/linting**: new code should pass `black --check` and
  `flake8 --config=setup.cfg` (see `pyproject.toml` / `setup.cfg`). The
  pre-existing `app.py`/`db.py`/`services/*.py` weren't reformatted in this
  pass — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Further Reading

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — diagrams + design decisions
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — deployment guide
- [docs/AUDIT.md](docs/AUDIT.md) — production readiness audit: what was
  fixed, what was deliberately deferred, and why
