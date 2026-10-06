#!/usr/bin/env python3
"""
scripts/backup_db.py
=====================
Creates a timestamped copy of the SQLite database using SQLite's own online
backup API (sqlite3.Connection.backup) rather than a raw file copy, so a
backup taken while the app is running is guaranteed to be consistent (a
plain `cp` of a live SQLite file can capture a half-written page).

Usage:
    python scripts/backup_db.py [--keep N]

    --keep N   Delete backups older than the N most recent (default: keep all)
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

BACKUP_DIR = os.environ.get("ISIS_BACKUP_DIR", "backups")


def backup():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=int, default=None, help="Keep only the N most recent backups")
    args = parser.parse_args()

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"isis_portfolio_{timestamp}.db")

    source = sqlite3.connect(db.DB_PATH)
    dest = sqlite3.connect(backup_path)
    with dest:
        source.backup(dest)
    source.close()
    dest.close()

    size_kb = os.path.getsize(backup_path) / 1024
    print(f"Backed up {db.DB_PATH} -> {backup_path} ({size_kb:.1f} KB)")

    if args.keep:
        backups = sorted(
            (f for f in os.listdir(BACKUP_DIR) if f.startswith("isis_portfolio_") and f.endswith(".db")),
            reverse=True,
        )
        for old in backups[args.keep :]:
            os.remove(os.path.join(BACKUP_DIR, old))
            print(f"Removed old backup: {old}")


if __name__ == "__main__":
    backup()
