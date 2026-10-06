# Deployment Guide

## Prerequisites

- Docker + Docker Compose (recommended), or Python 3.12 for a bare-metal install
- A reverse proxy for TLS termination in production (nginx, Caddy, or a cloud
  load balancer) — the container itself serves plain HTTP

## Environment Setup

```bash
cp .env.example .env
```

At minimum, set in `.env`:
- `ISIS_ENV=production`
- `ISIS_SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `SESSION_COOKIE_SECURE=true` — **only** once TLS termination is actually in front of the app
- `GEMINI_API_KEY` — optional; both AI features (activity analysis, Copilot) have a working local fallback without it

## Docker (recommended)

```bash
docker compose up -d --build
docker compose logs -f isis          # tail logs
docker compose exec isis python scripts/seed_db.py   # optional demo data
```

The container:
- Runs as a non-root user
- Serves via gunicorn (2 workers by default — tune with `GUNICORN_WORKERS`)
- Persists the SQLite database at `/app/instance` and logs at `/app/logs`
  in named Docker volumes, so `docker compose down && docker compose up`
  doesn't lose data
- Has a `HEALTHCHECK` hitting `/healthz` (DB connectivity check)

### Scaling notes

This app's rate limiter (`Flask-Limiter`) defaults to in-memory storage
(`RATELIMIT_STORAGE_URI=memory://`), which means each gunicorn *worker*
enforces its own separate limit — fine for a single container with a couple
of workers, but if you ever run multiple *replicas* behind a load balancer,
point `RATELIMIT_STORAGE_URI` at a shared Redis instance instead, or the
effective rate limit becomes (configured limit × replica count).

SQLite itself handles concurrent reads well but serializes writes — this is
fine for the traffic levels this app is built for (a personal/small-team
career tool, not a high-write multi-tenant SaaS). See
[docs/ARCHITECTURE.md](ARCHITECTURE.md) for the reasoning behind not doing
a full Postgres migration in this pass, and what's already in place
(`DATABASE_URL` in `config.py`) if that migration is done later.

## Bare-metal (no Docker)

```bash
pip install -r requirements.txt
export ISIS_ENV=production
export ISIS_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 app:app
```

Do **not** run `python app.py` in production — that starts Flask's
development server, which the app itself warns against on startup.

## Backups

```bash
python scripts/backup_db.py --keep 14   # keep the 14 most recent backups
```

Uses SQLite's own online backup API (not a raw file copy), so a backup
taken while the app is running is guaranteed consistent. Schedule via cron
or a Docker Compose sidecar/`docker exec` from your orchestrator of choice.

## Verifying a Deployment

```bash
curl http://localhost:5000/healthz
# {"status": "ok", "database": "ok", "gemini_configured": true}
```

`/health` (no `z`) also exists as a simpler legacy liveness ping that
predates `/healthz` — both are harmless to keep; `/healthz` is the more
thorough one (actually checks DB connectivity) and is what the
`HEALTHCHECK`/CI use.
