"""
repositories/history_repository.py
===================================
Wraps db.py's activity-log functions — the "History" page and every AI
engine (scoring, ATS, skill gap, Copilot) reads through this same data.
"""

import db


class HistoryRepository:
    """The user's logged activities — the core record this whole app is built on."""

    def add_activity(self, *args, **kwargs):
        """
        Thin passthrough to db.insert_activity(...) — deliberately forwards
        *args/**kwargs rather than re-declaring its full parameter list here,
        so this wrapper can never silently drift out of sync with the real
        function's contract. See db.insert_activity's docstring/signature
        for the exact parameters.
        """
        return db.insert_activity(*args, **kwargs)

    def get_all_for_user(self, user_id) -> list[dict]:
        return db.get_user_activities(user_id)

    def get_aggregated_metrics(self, user_id) -> dict:
        return db.get_aggregated_metrics(user_id)
