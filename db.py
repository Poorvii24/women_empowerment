"""
db.py - Database initialization and helper functions for the ISIS backend.
Uses SQLite for lightweight, persistent storage of user activities and skill mappings.
"""
import json
import logging
import os
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger("isis.db")

# Respects ISIS_DB_PATH (needed so the Docker volume mount at /app/instance
# actually persists data — see Dockerfile/docker-compose.yml). Falls back to
# the exact same default as before when unset, so existing local/dev setups
# are unaffected.
DB_PATH = os.environ.get("ISIS_DB_PATH") or os.path.join(os.path.dirname(__file__), "isis_portfolio.db")


def get_connection():
    """Opens and returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
    return conn


@contextmanager
def _connection():
    """
    Context manager that guarantees the connection is always closed,
    even if the query inside raises. Does not swallow exceptions —
    callers still see and can log/handle the original error.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _to_iso_utc(sqlite_timestamp: str) -> str:
    """
    SQLite's CURRENT_TIMESTAMP produces a bare 'YYYY-MM-DD HH:MM:SS' string in
    UTC, with no timezone marker at all. When that string is handed to
    JavaScript's `new Date(...)` on the frontend, browsers treat the
    space-separated (non-ISO-8601) format as LOCAL time rather than UTC —
    silently shifting every displayed timestamp by the user's UTC offset
    (e.g. 5.5 hours early for IST). Converting to explicit ISO-8601 with a
    'Z' suffix here removes the ambiguity, so the browser correctly treats
    it as UTC and converts to the viewer's local time itself.
    """
    if not sqlite_timestamp:
        return sqlite_timestamp
    return sqlite_timestamp.replace(" ", "T") + "Z"


def init_db():
    """
    Initializes the database and creates all required tables.
    Also runs migrations to add new columns to existing tables.

    Schema (activities):
        id, user_id, input_activity, mapped_skill, onet_category,
        leadership_category, skill_magnitude, market_value, created_at,
        -- NEW --
        career_equivalency   TEXT  (e.g. 'Junior Project Manager')
        radar_strategic      REAL
        radar_financial      REAL
        radar_crisis         REAL
        radar_team           REAL
        radar_emotional      REAL
        leadership_index     REAL
        employability_score  REAL
        skills_mapped        TEXT  (JSON array stored as string)
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Create primary table with full schema (safe IF NOT EXISTS)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             TEXT NOT NULL,
                input_activity      TEXT NOT NULL,
                mapped_skill        TEXT NOT NULL,
                onet_category       TEXT,
                leadership_category TEXT,
                skill_magnitude     REAL NOT NULL DEFAULT 0.0,
                market_value        TEXT,
                created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                career_equivalency  TEXT,
                radar_strategic     REAL DEFAULT 0,
                radar_financial     REAL DEFAULT 0,
                radar_crisis        REAL DEFAULT 0,
                radar_team          REAL DEFAULT 0,
                radar_emotional     REAL DEFAULT 0,
                leadership_index    REAL DEFAULT 0,
                employability_score REAL DEFAULT 0,
                skills_mapped       TEXT DEFAULT '[]',
                resume_snippet      TEXT DEFAULT ''
            )
        """)

        # Create users table for authentication
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Safely add new columns to existing DB without breaking anything
        new_columns = [
            ("career_equivalency",  "TEXT DEFAULT ''"),
            ("radar_strategic",     "REAL DEFAULT 0"),
            ("radar_financial",     "REAL DEFAULT 0"),
            ("radar_crisis",        "REAL DEFAULT 0"),
            ("radar_team",          "REAL DEFAULT 0"),
            ("radar_emotional",     "REAL DEFAULT 0"),
            ("leadership_index",    "REAL DEFAULT 0"),
            ("employability_score", "REAL DEFAULT 0"),
            ("skills_mapped",       "TEXT DEFAULT '[]'"),
            ("resume_snippet",      "TEXT DEFAULT ''"),  # added for résumé feed deduplication
            # Phase 3 — embedding-based NLP engine explainability (additive, nullable)
            ("nlp_primary_skill",     "TEXT DEFAULT ''"),
            ("nlp_confidence_pct",    "REAL DEFAULT 0"),
            ("nlp_similarity_score",  "REAL DEFAULT 0"),
            ("nlp_matched_phrase",    "TEXT DEFAULT ''"),
            ("fusion_method",         "TEXT DEFAULT ''"),
        ]
        for col_name, col_def in new_columns:
            try:
                cursor.execute(f"ALTER TABLE activities ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                pass  # Column already exists — skip silently

        # Create notifications table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                message    TEXT NOT NULL,
                link       TEXT DEFAULT '#',
                is_read    INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Phase 4 — Career Intelligence Platform tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT NOT NULL,
                filename      TEXT NOT NULL,
                raw_text      TEXT NOT NULL,
                skills_text   TEXT DEFAULT '',
                projects_text TEXT DEFAULT '',
                education_text TEXT DEFAULT '',
                experience_text TEXT DEFAULT '',
                certifications_text TEXT DEFAULT '',
                candidate_skills TEXT DEFAULT '[]',
                uploaded_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_targets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL UNIQUE,
                target_role TEXT NOT NULL,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # AI Career Copilot — conversation history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS copilot_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes on user_id — every hot-path query in this app filters by
        # user_id (get_user_activities, get_notifications, get_latest_resume,
        # get_copilot_history, ...). Safe/additive: CREATE INDEX IF NOT
        # EXISTS is idempotent and doesn't change any existing data or query
        # results, only how fast SQLite can find them.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_user_id ON activities(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_resumes_user_id ON resumes(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_copilot_messages_user_id ON copilot_messages(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

        conn.commit()
        conn.close()
        logger.info("db_initialized", extra={"db_path": DB_PATH})
    except sqlite3.Error:
        logger.critical("db_initialization_failed", exc_info=True, extra={"db_path": DB_PATH})
        raise RuntimeError(
            f"Could not initialize the database at {DB_PATH}. "
            "Check file permissions and disk space. ISIS cannot start without it."
        )


def insert_activity(user_id, input_activity, mapped_skill, onet_category,
                    leadership_category, skill_magnitude, market_value,
                    career_equivalency="", radar_strategic=0, radar_financial=0,
                    radar_crisis=0, radar_team=0, radar_emotional=0,
                    leadership_index=0, employability_score=0, skills_mapped=None,
                    resume_snippet="", nlp_primary_skill="", nlp_confidence_pct=0,
                    nlp_similarity_score=0, nlp_matched_phrase="", fusion_method=""):
    """Inserts a new analyzed activity record into the database."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO activities 
                (user_id, input_activity, mapped_skill, onet_category, leadership_category,
                 skill_magnitude, market_value, career_equivalency,
                 radar_strategic, radar_financial, radar_crisis, radar_team, radar_emotional,
                 leadership_index, employability_score, skills_mapped, resume_snippet,
                 nlp_primary_skill, nlp_confidence_pct, nlp_similarity_score,
                 nlp_matched_phrase, fusion_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, input_activity, mapped_skill, onet_category, leadership_category,
                skill_magnitude, market_value, career_equivalency,
                radar_strategic, radar_financial, radar_crisis, radar_team, radar_emotional,
                leadership_index, employability_score,
                json.dumps(skills_mapped or []),
                resume_snippet,
                nlp_primary_skill, nlp_confidence_pct, nlp_similarity_score,
                nlp_matched_phrase, fusion_method,
            ))
            last_id = cursor.lastrowid
            conn.commit()
            return last_id
    except sqlite3.Error:
        logger.exception("insert_activity_failed", extra={"user_id": user_id})
        raise


def get_user_activities(user_id):
    """Retrieves all activities for a given user, ordered by most recent."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM activities
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 50
            """, (user_id,))
            rows = []
            for row in cursor.fetchall():
                r = dict(row)
                # Deserialize skills_mapped from JSON string
                try:
                    r["skills_mapped"] = json.loads(r.get("skills_mapped") or "[]")
                except (json.JSONDecodeError, TypeError):
                    r["skills_mapped"] = []
                # Normalize timestamp to ISO-8601 UTC so JS Date() parses it correctly
                if r.get("created_at"):
                    r["created_at"] = _to_iso_utc(r["created_at"])
                rows.append(r)
            return rows
    except sqlite3.Error:
        logger.exception("get_user_activities_failed", extra={"user_id": user_id})
        raise


def get_aggregated_metrics(user_id):
    """
    Computes aggregated dashboard metrics for a user.
    Returns averaged radar scores per dimension for Chart.js.
    """
    try:
        with _connection() as conn:
            cursor = conn.cursor()

            # Per-category magnitudes (legacy leadership_category grouping)
            cursor.execute("""
                SELECT 
                    leadership_category,
                    AVG(skill_magnitude) as avg_magnitude,
                    COUNT(*) as count
                FROM activities
                WHERE user_id = ?
                GROUP BY leadership_category
            """, (user_id,))
            category_data = [dict(row) for row in cursor.fetchall()]

            # Averaged 5-point radar dimensions across all activities
            cursor.execute("""
                SELECT 
                    AVG(radar_strategic)    as avg_strategic,
                    AVG(radar_financial)    as avg_financial,
                    AVG(radar_crisis)       as avg_crisis,
                    AVG(radar_team)         as avg_team,
                    AVG(radar_emotional)    as avg_emotional,
                    AVG(leadership_index)   as avg_leadership_index,
                    AVG(employability_score) as avg_employability_score,
                    COUNT(*)                as total
                FROM activities
                WHERE user_id = ?
            """, (user_id,))
            agg = dict(cursor.fetchone())

            # Latest 5 *unique* activities (dedup on resume_snippet) for the Resume Feed
            # Uses a subquery to pick the most recent row for each distinct resume_snippet,
            # then limits to 5 so the feed and PDF never contain repeated bullets.
            cursor.execute("""
                SELECT mapped_skill, resume_snippet, career_equivalency, skills_mapped,
                       market_value, created_at, nlp_primary_skill, nlp_confidence_pct,
                       nlp_similarity_score, nlp_matched_phrase, fusion_method
                FROM (
                    SELECT *, MAX(created_at) as last_seen
                    FROM activities
                    WHERE user_id = ?
                    GROUP BY resume_snippet          -- deduplicate by bullet text
                ) AS deduped
                ORDER BY last_seen DESC
                LIMIT 5
            """, (user_id,))
            recent_raw = cursor.fetchall()
    except sqlite3.Error:
        logger.exception("get_aggregated_metrics_failed", extra={"user_id": user_id})
        raise

    def safe(v): return round(v, 2) if (v is not None and v == v) else 0.0

    # Deserialise skills_mapped JSON string -> list
    recent_activities = []
    for row in recent_raw:
        act = dict(row)
        if act.get("skills_mapped"):
            try:
                act["skills_mapped"] = json.loads(act["skills_mapped"])
            except (ValueError, TypeError):
                act["skills_mapped"] = []
        recent_activities.append(act)

    return {
        "category_breakdown": category_data,
        "total_activities": agg["total"] or 0,
        "overall_avg_magnitude": safe(agg["avg_employability_score"]),
        "radar_averages": {
            "Strategic":  safe(agg["avg_strategic"]),
            "Financial":  safe(agg["avg_financial"]),
            "Crisis":     safe(agg["avg_crisis"]),
            "Team":       safe(agg["avg_team"]),
            "Emotional":  safe(agg["avg_emotional"])
        },
        "avg_leadership_index":    safe(agg["avg_leadership_index"]),
        "avg_employability_score": safe(agg["avg_employability_score"]),
        "recent_activities": recent_activities
    }


# ---------------------------------------------------------------------------
# User / Auth Helpers
# ---------------------------------------------------------------------------

def create_user(username: str, password_hash: str):
    """Insert a new user. Returns the new user's id, or None if username exists."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username.strip().lower(), password_hash)
            )
            conn.commit()
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Expected, documented case: username already exists (UNIQUE constraint).
        logger.info("create_user_duplicate_username")
        return None
    except sqlite3.Error:
        # Anything else (disk full, locked DB, permissions, etc.) is a real
        # failure — log it and let the caller's generic error handler take over,
        # rather than silently reporting it as "username already taken".
        logger.exception("create_user_failed")
        raise


def get_user_by_username(username: str):
    """Fetch a user row by username (case-insensitive). Returns dict or None."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE LOWER(username) = ?",
                (username.strip().lower(),)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except sqlite3.Error:
        logger.exception("get_user_by_username_failed")
        raise


def get_user_by_id(user_id: int):
    """Fetch a user row by primary key. Returns dict or None."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except sqlite3.Error:
        logger.exception("get_user_by_id_failed", extra={"user_id": user_id})
        raise


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------
def add_notification(user_id, message, link="#"):
    """Insert a new unread notification for the given user."""
    try:
        with _connection() as conn:
            conn.execute(
                "INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)",
                (str(user_id), message, link)
            )
            conn.commit()
    except sqlite3.Error:
        # Notifications are a non-critical side effect of analyze_activity —
        # log and swallow so a notification failure never breaks the main
        # activity analysis flow the user is actually waiting on.
        logger.exception("add_notification_failed", extra={"user_id": user_id})


def get_notifications(user_id, limit=10):
    """Return the most recent notifications for a user, newest first."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, message, link, is_read, created_at FROM notifications "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (str(user_id), limit)
            )
            rows = [dict(r) for r in cursor.fetchall()]
            for row in rows:
                row["created_at"] = _to_iso_utc(row["created_at"])
            return rows
    except sqlite3.Error:
        logger.exception("get_notifications_failed", extra={"user_id": user_id})
        raise


def get_unread_count(user_id):
    """Return count of unread notifications for the given user."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = ? AND is_read = 0",
                (str(user_id),)
            )
            row = cursor.fetchone()
            return row["cnt"] if row else 0
    except sqlite3.Error:
        logger.exception("get_unread_count_failed", extra={"user_id": user_id})
        raise


def mark_all_read(user_id):
    """Mark every unread notification for a user as read."""
    try:
        with _connection() as conn:
            conn.execute(
                "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
                (str(user_id),)
            )
            conn.commit()
    except sqlite3.Error:
        # Non-critical: failing to mark notifications as read shouldn't break
        # the page/endpoint that triggered it.
        logger.exception("mark_all_read_failed", extra={"user_id": user_id})


# ---------------------------------------------------------------------------
# Phase 4 — Career Intelligence Platform helpers
# ---------------------------------------------------------------------------

def save_resume(user_id: str, filename: str, parsed: dict) -> int:
    """Saves a parsed resume to the DB. Returns the new resume row id."""
    import json as _json
    sections = parsed.get("sections", {})
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO resumes
                  (user_id, filename, raw_text, skills_text, projects_text,
                   education_text, experience_text, certifications_text, candidate_skills)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(user_id),
                filename,
                parsed.get("raw_text", ""),
                sections.get("skills", ""),
                sections.get("projects", ""),
                sections.get("education", ""),
                sections.get("experience", ""),
                sections.get("certifications", ""),
                _json.dumps(parsed.get("candidate_skills", [])),
            ))
            conn.commit()
            return cursor.lastrowid
    except sqlite3.Error:
        logger.exception("save_resume_failed", extra={"user_id": user_id})
        raise


def get_latest_resume(user_id: str) -> dict | None:
    """Returns the most recently uploaded resume for the user, or None."""
    import json as _json
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM resumes WHERE user_id = ? ORDER BY uploaded_at DESC LIMIT 1",
                (str(user_id),)
            )
            row = cursor.fetchone()
            if not row:
                return None
            r = dict(row)
            try:
                r["candidate_skills"] = _json.loads(r.get("candidate_skills") or "[]")
            except (ValueError, TypeError):
                r["candidate_skills"] = []
            return r
    except sqlite3.Error:
        logger.exception("get_latest_resume_failed", extra={"user_id": user_id})
        raise


def set_user_target_role(user_id: str, role: str) -> None:
    """Upserts the user's chosen target career role."""
    try:
        with _connection() as conn:
            conn.execute("""
                INSERT INTO user_targets (user_id, target_role, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                  target_role = excluded.target_role,
                  updated_at  = CURRENT_TIMESTAMP
            """, (str(user_id), role))
            conn.commit()
    except sqlite3.Error:
        logger.exception("set_user_target_role_failed", extra={"user_id": user_id})
        raise


def get_user_target_role(user_id: str) -> str | None:
    """Returns the user's target role or None if not set yet."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT target_role FROM user_targets WHERE user_id = ?",
                (str(user_id),)
            )
            row = cursor.fetchone()
            return row["target_role"] if row else None
    except sqlite3.Error:
        logger.exception("get_user_target_role_failed", extra={"user_id": user_id})
        raise


# ---------------------------------------------------------------------------
# AI Career Copilot — conversation history
# ---------------------------------------------------------------------------

def insert_copilot_message(user_id: str, role: str, content: str) -> None:
    """Appends one message (role='user' or 'assistant') to the Copilot's
    per-user conversation history."""
    try:
        with _connection() as conn:
            conn.execute(
                "INSERT INTO copilot_messages (user_id, role, content) VALUES (?, ?, ?)",
                (str(user_id), role, content)
            )
            conn.commit()
    except sqlite3.Error:
        logger.exception("insert_copilot_message_failed", extra={"user_id": user_id})
        raise


def get_copilot_history(user_id: str, limit: int = 20) -> list[dict]:
    """Returns the most recent Copilot messages for this user, oldest first."""
    try:
        with _connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role, content, created_at FROM copilot_messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (str(user_id), limit))
            rows = [dict(r) for r in cursor.fetchall()]
            rows.reverse()
            for r in rows:
                r["created_at"] = _to_iso_utc(r["created_at"])
            return rows
    except sqlite3.Error:
        logger.exception("get_copilot_history_failed", extra={"user_id": user_id})
        raise


def clear_copilot_history(user_id: str) -> None:
    """Deletes all Copilot conversation history for this user."""
    try:
        with _connection() as conn:
            conn.execute("DELETE FROM copilot_messages WHERE user_id = ?", (str(user_id),))
            conn.commit()
    except sqlite3.Error:
        logger.exception("clear_copilot_history_failed", extra={"user_id": user_id})
        raise
