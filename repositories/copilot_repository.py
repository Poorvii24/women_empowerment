"""
repositories/copilot_repository.py
===================================
Wraps db.py's Copilot conversation-history functions.
"""

import db


class CopilotRepository:
    """AI Career Copilot conversation history."""

    def add_message(self, user_id: str, role: str, content: str) -> None:
        db.insert_copilot_message(user_id, role, content)

    def get_history(self, user_id: str, limit: int = 20) -> list[dict]:
        return db.get_copilot_history(user_id, limit=limit)

    def clear(self, user_id: str) -> None:
        db.clear_copilot_history(user_id)
