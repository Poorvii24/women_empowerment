"""
repositories/user_repository.py
================================
Wraps db.py's user account and target-role functions.
"""

import db


class UserRepository:
    """User accounts and target-role preferences."""

    def create(self, username: str, password_hash: str) -> int:
        """Creates a new user, returns the new user id. Raises
        sqlite3.IntegrityError if the username is already taken (unchanged
        from db.create_user's existing behavior)."""
        return db.create_user(username, password_hash)

    def get_by_username(self, username: str) -> dict | None:
        return db.get_user_by_username(username)

    def get_by_id(self, user_id) -> dict | None:
        return db.get_user_by_id(user_id)

    def set_target_role(self, user_id: str, role: str) -> None:
        db.set_user_target_role(user_id, role)

    def get_target_role(self, user_id: str) -> str | None:
        return db.get_user_target_role(user_id)
