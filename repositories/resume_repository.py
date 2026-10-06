"""
repositories/resume_repository.py
==================================
Wraps db.py's resume storage functions.
"""

import db


class ResumeRepository:
    """Uploaded resume storage and retrieval."""

    def save(self, user_id: str, filename: str, parsed: dict) -> int:
        """Stores a newly parsed resume, returns the new resume row id."""
        return db.save_resume(user_id, filename, parsed)

    def get_latest(self, user_id: str) -> dict | None:
        return db.get_latest_resume(user_id)
