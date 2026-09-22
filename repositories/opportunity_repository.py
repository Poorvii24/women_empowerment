"""
repositories/opportunity_repository.py
=======================================
Wraps db.py's notifications functions. Per project_overview.txt, these
notifications ARE the Opportunity Engine's output (opportunities surfaced
to the user as they log activities), so this repository is named for that
concept rather than the underlying "notifications" table name.
"""

import db


class OpportunityRepository:
    """Opportunity Engine alerts (stored in the notifications table)."""

    def add(self, user_id, message, link="#"):
        return db.add_notification(user_id, message, link)

    def get_recent(self, user_id, limit=10) -> list[dict]:
        return db.get_notifications(user_id, limit=limit)

    def get_unread_count(self, user_id) -> int:
        return db.get_unread_count(user_id)

    def mark_all_read(self, user_id) -> None:
        db.mark_all_read(user_id)
