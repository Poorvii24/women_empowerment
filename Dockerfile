# syntax=docker/dockerfile:1
# =============================================================================
# ISIS Career Intelligence Platform — production container image
# =============================================================================
# Multi-stage build: the builder stage installs Python dependencies (including
# the heavier sentence-transformers/torch stack) into a virtualenv; the final
# runtime stage copies only that virtualenv + app code, keeping the shipped
# image smaller and avoiding build tools in the production image.

FROM python:3.12-slim AS builder

WORKDIR /build

# System packages needed only to *build* some Python wheels (e.g. sentence-
# transformers' dependencies) — not present in the final runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && python -m nltk.downloader -d /opt/venv/nltk_data \
       punkt_tab averaged_perceptron_tagger_eng stopwords wordnet omw-1.4

ENV NLTK_DATA=/opt/venv/nltk_data


FROM python:3.12-slim AS runtime

# curl is used by the HEALTHCHECK below to call /healthz
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user
RUN useradd --create-home --shell /bin/bash isis
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --chown=isis:isis . .

# Writable locations for the SQLite database and rotating log files — mount
# these as volumes in docker-compose.yml so data survives container restarts.
RUN mkdir -p /app/logs /app/instance \
    && chown -R isis:isis /app/logs /app/instance

USER isis

ENV ISIS_ENV=production \
    ISIS_HOST=0.0.0.0 \
    ISIS_PORT=5000 \
    ISIS_LOG_DIR=/app/logs \
    ISIS_DB_PATH=/app/instance/isis_portfolio.db \
    NLTK_DATA=/opt/venv/nltk_data \
    PYTHONUNBUFFERED=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/healthz || exit 1

# gunicorn, not the Flask dev server — see requirements.txt comment.
# --workers 2: reasonable default for a small deployment; tune via
# GUNICORN_WORKERS in docker-compose.yml for larger ones.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5000 --workers ${GUNICORN_WORKERS:-2} --timeout 120 --access-logfile - --error-logfile - app:app"]
