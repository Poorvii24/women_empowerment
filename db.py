"""
db.py - Database initialization and helper functions for the ISIS backend.
Uses SQLite for lightweight, persistent storage of user activities and skill mappings.
"""
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "isis_portfolio.db")


def get_connection():
    """Opens and returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
    return conn


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
    conn = get_connection()
    cursor = conn.cursor()

    # Create primary table with full schema (safe IF NOT EXISTS)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             TEXT NOT NULL DEFAULT 'default_user',
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

    conn.commit()
    conn.close()
    print("[DB] Database initialized successfully at:", DB_PATH)


def insert_activity(user_id, input_activity, mapped_skill, onet_category,
                    leadership_category, skill_magnitude, market_value,
                    career_equivalency="", radar_strategic=0, radar_financial=0,
                    radar_crisis=0, radar_team=0, radar_emotional=0,
                    leadership_index=0, employability_score=0, skills_mapped=None,
                    resume_snippet=""):
    """Inserts a new analyzed activity record into the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO activities 
        (user_id, input_activity, mapped_skill, onet_category, leadership_category,
         skill_magnitude, market_value, career_equivalency,
         radar_strategic, radar_financial, radar_crisis, radar_team, radar_emotional,
         leadership_index, employability_score, skills_mapped, resume_snippet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, input_activity, mapped_skill, onet_category, leadership_category,
        skill_magnitude, market_value, career_equivalency,
        radar_strategic, radar_financial, radar_crisis, radar_team, radar_emotional,
        leadership_index, employability_score,
        json.dumps(skills_mapped or []),
        resume_snippet
    ))
    last_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return last_id


def get_user_activities(user_id="default_user"):
    """Retrieves all activities for a given user, ordered by most recent."""
    conn = get_connection()
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
        rows.append(r)
    conn.close()
    return rows


def get_aggregated_metrics(user_id="default_user"):
    """
    Computes aggregated dashboard metrics for a user.
    Returns averaged radar scores per dimension for Chart.js.
    """
    conn = get_connection()
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
               market_value, created_at
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

    conn.close()

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
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username.strip().lower(), password_hash)
        )
        conn.commit()
        return cursor.lastrowid
    except Exception:
        return None
    finally:
        conn.close()


def get_user_by_username(username: str):
    """Fetch a user row by username (case-insensitive). Returns dict or None."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM users WHERE LOWER(username) = ?",
        (username.strip().lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int):
    """Fetch a user row by primary key. Returns dict or None."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------
def add_notification(user_id, message, link="#"):
    """Insert a new unread notification for the given user."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)",
            (str(user_id), message, link)
        )
        conn.commit()
    finally:
        conn.close()


def get_notifications(user_id, limit=10):
    """Return the most recent notifications for a user, newest first."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, message, link, is_read, created_at FROM notifications "
        "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (str(user_id), limit)
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_unread_count(user_id):
    """Return count of unread notifications for the given user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = ? AND is_read = 0",
        (str(user_id),)
    )
    row = cursor.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def mark_all_read(user_id):
    """Mark every unread notification for a user as read."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
            (str(user_id),)
        )
        conn.commit()
    finally:
        conn.close()

