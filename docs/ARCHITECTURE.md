# Architecture

## System Architecture

```mermaid
graph TB
    subgraph Client["Browser"]
        UI[index.html / career.html / history.html]
        Widget[copilot_widget.js]
    end

    subgraph Flask["Flask Application (app.py)"]
        Routes[Routes — thin: auth, validation, delegate]
        AfterReq[after_request: security headers]
        ErrHandlers[Centralized error handlers]
    end

    subgraph Logic["Application Layer"]
        Repos[repositories/ — DB access wrappers]
        Services[services/ — business logic]
        Utils[utils/ — validators, response helpers]
    end

    subgraph Data["Persistence"]
        DB[(SQLite — db.py)]
    end

    subgraph External["External / Optional"]
        Gemini[Gemini API]
        HF[huggingface.co — sentence-transformers model]
    end

    UI -->|fetch + session cookie + CSRF| Routes
    Widget -->|fetch /copilot/*| Routes
    Routes --> AfterReq
    Routes --> ErrHandlers
    Routes --> Repos
    Routes --> Services
    Routes --> Utils
    Repos --> DB
    Services --> DB
    Services -.optional.-> Gemini
    Services -.cached after first pull.-> HF
```

## Request Flow (example: AI Copilot)

```mermaid
sequenceDiagram
    participant B as Browser
    participant R as Flask Route (/copilot/ask)
    participant V as utils/validators
    participant C as services/ai_copilot
    participant Repo as repositories/*
    participant DB as db.py (SQLite)
    participant G as Gemini API

    B->>R: POST /copilot/ask {message}
    R->>V: validate_string_length(message)
    alt invalid
        V-->>R: ValidationError
        R-->>B: 400 {status: error}
    else valid
        R->>C: ask(user_id, message, gemini_client)
        C->>Repo: build_user_context (scoring, ATS, skill gap, roadmap, opportunities)
        Repo->>DB: read activities / resume / target role
        DB-->>Repo: rows
        Repo-->>C: context dict
        C->>G: generate_content(prompt + context) [if configured]
        alt Gemini available
            G-->>C: structured JSON answer
        else Gemini unavailable/fails
            C->>C: local rule-based fallback (same context, never fabricates)
        end
        C->>DB: persist conversation turn
        C-->>R: {answer, evidence, confidence, next_action, ...}
        R-->>B: 200 {status: ok, ...}
    end
```

## AI Pipeline

```mermaid
graph LR
    Activity[Logged Activity] --> Gemini{Gemini configured?}
    Gemini -->|yes| GAnalysis[Gemini: map to skill + score]
    Gemini -->|no / fails| LocalNLP[Local NLP fallback]
    LocalNLP --> Embed[nlp/embedding_engine.py]
    Embed --> Cache{Cached locally?}
    Cache -->|yes| Encode[Encode — zero network calls]
    Cache -->|no| Download[Download from huggingface.co, then cache]
    Encode --> Match[skill_matcher: cosine similarity]
    Download --> Match
    GAnalysis --> Stored[(activities table:\nmapped_skill, career_equivalency,\nemployability_score, leadership_index)]
    Match --> Stored

    Stored --> Scoring[scoring_engine: 5-axis Career Readiness]
    Stored --> GapEngine[skill_gap_engine: vs. target role]
    Scoring --> Snapshot[Career Snapshot / Copilot / PDFs]
    GapEngine --> Snapshot
    GapEngine --> Roadmap[learning_recommender: 30/60/90 plan]
    GapEngine --> Opportunities[opportunity_recommender]
```

## Database Interactions (ERD)

```mermaid
erDiagram
    USERS ||--o{ ACTIVITIES : logs
    USERS ||--o| RESUMES : uploads
    USERS ||--o| USER_TARGETS : sets
    USERS ||--o{ NOTIFICATIONS : receives
    USERS ||--o{ COPILOT_MESSAGES : chats

    USERS {
        int id PK
        string username UK
        string password_hash
        datetime created_at
    }
    ACTIVITIES {
        int id PK
        string user_id FK
        string mapped_skill
        string career_equivalency
        string market_value
        float employability_score
        float leadership_index
        string resume_snippet
        datetime created_at
    }
    RESUMES {
        int id PK
        string user_id FK
        string filename
        text raw_text
        text projects_text
        text candidate_skills
        datetime uploaded_at
    }
    USER_TARGETS {
        int id PK
        string user_id UK,FK
        string target_role
    }
    NOTIFICATIONS {
        int id PK
        string user_id FK
        string message
        bool is_read
    }
    COPILOT_MESSAGES {
        int id PK
        string user_id FK
        string role
        text content
        datetime created_at
    }
```

## Service Layer

```mermaid
graph TB
    subgraph Routes["app.py routes"]
        direction TB
        R1[career_analysis]
        R2[generate_pdf]
        R3[career_portfolio_pdf]
        R4[copilot_ask]
    end

    subgraph Services["services/"]
        SGE[skill_gap_engine]
        SE[scoring_engine]
        ATS[ats_engine]
        LR[learning_recommender]
        OR[opportunity_recommender]
        PD[pdf_design]
        AC[ai_copilot]
    end

    R1 --> SGE & SE & ATS & LR
    R2 --> SE & LR & OR & PD
    R3 --> SGE & SE & ATS & LR & OR & PD
    R4 --> AC
    AC --> SE & ATS & SGE & LR & OR
```

## Deployment Architecture

```mermaid
graph TB
    subgraph Internet
        User[Browser]
    end

    subgraph Docker["Docker host"]
        subgraph Container["isis container (gunicorn, 2+ workers)"]
            App[Flask app]
        end
        VolDB[(Volume: /app/instance\nSQLite file)]
        VolLogs[(Volume: /app/logs\napp/error/security/ai_inference.log)]
    end

    User -->|HTTPS, terminated upstream| Container
    Container --> VolDB
    Container --> VolLogs
    App -.optional.-> GeminiAPI[Gemini API]
    App -.cached after first pull.-> HFHub[huggingface.co]
```

Note: this diagram assumes a reverse proxy (nginx/Caddy/a cloud load
balancer) in front of the container for TLS termination — the container
itself serves plain HTTP on port 5000. `SESSION_COOKIE_SECURE=true` should
only be set once that HTTPS termination is actually in place.

---

## Key Design Decisions & Scope Boundaries

This section is deliberately explicit about what was **not** done and why —
see also [docs/AUDIT.md](AUDIT.md) for the full production-readiness audit.

### Database: SQLite kept, full Postgres/SQLAlchemy migration not done

Rewriting `db.py`'s ~30 functions (raw `sqlite3`) onto SQLAlchemy to support
both SQLite and Postgres would touch the single most business-critical,
already-working file in the app, with no automated migration-correctness
net beyond the test suite added in this pass. Given the brief's own top
priority — preserve all functionality — this was judged too high-risk to
do as a blind rewrite in one pass. Instead:
- `config.py`'s `DATABASE_URL` is already wired up for a future SQLAlchemy
  implementation to read.
- `db.DB_PATH` now respects `ISIS_DB_PATH` (previously hardcoded), which is
  what actually makes the Docker volume / backup script work today.
- Indexes were added on every `user_id` column (the actual hot path).
- `scripts/backup_db.py` and `scripts/seed_db.py` cover the "backup
  strategy" and "seed scripts" asks without needing the ORM migration.

### Repository pattern: added, not retrofitted onto all ~80 call sites

`repositories/` wraps `db.py` behind clean interfaces. `set_target_role`
and the Copilot routes were migrated to prove the pattern end-to-end and
are fully covered by tests. The remaining ~75 `db.*` call sites across
`app.py` were **not** all migrated — that's a mechanical but large-diff
change across a 2,300-line file, and the value (nicer call sites) doesn't
justify the regression surface for a file with no other correctness net
beyond manual testing before this pass. Recommended as the pattern for all
new routes going forward.

### Auth: hardened session auth kept; JWT/RBAC not bolted on

The existing Flask-Login session auth was already solid (CSRF everywhere,
`HttpOnly`/`SameSite` cookies, password hashing, rate limiting). Replacing
it with JWT would mean rewriting every `@login_required` route and the
frontend's fetch calls, for an app that has exactly one user role and no
multi-service/mobile-client need for stateless tokens today. That's a
large, purely speculative rewrite with real regression risk and no proven
requirement driving it — skipped. Security headers (Task 6's other ask)
*were* added, since that's genuinely additive and zero-risk.

### Code quality: new modules formatted, legacy files left as-is

`black`/`flake8` are configured and pass cleanly on every module added in
this pass. The pre-existing `app.py`/`db.py`/`services/*.py` (207
pre-existing style violations, mostly spacing/blank-lines) were **not**
mass-reformatted — a repo-wide `black` run on files with real business
logic and no line-by-line review budget is exactly the kind of change the
brief's "do not change business logic unless necessary" warns against,
even though formatting is nominally behavior-preserving.
