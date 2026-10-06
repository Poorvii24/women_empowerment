#!/usr/bin/env python3
"""
scripts/seed_db.py
===================
Populates a fresh database with one demo user and a handful of realistic
logged activities, so a new deployment (or a fresh `docker compose up`) has
something to look at immediately instead of an empty dashboard.

This does NOT touch a database that already has this demo user — safe to
run multiple times.

Usage:
    python scripts/seed_db.py
    # or inside Docker:
    docker compose exec isis python scripts/seed_db.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash

import db

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "DemoPass123!"  # change immediately in any shared environment

DEMO_ACTIVITIES = [
    dict(
        input_activity="Organized a 3-day community food drive for 200+ families",
        mapped_skill="Logistics & Volunteer Coordination",
        onet_category="Administrative",
        leadership_category="Leadership",
        skill_magnitude=78,
        market_value="High",
        career_equivalency="Matches Operations Coordinator",
        leadership_index=75,
        employability_score=74,
        skills_mapped=["Logistics & Volunteer Coordination"],
        resume_snippet="Coordinated a 3-day community food drive, managing volunteers, "
        "inventory, and distribution logistics for 200+ families.",
    ),
    dict(
        input_activity="Managed the household budget and vendor negotiations for a family event",
        mapped_skill="Budget Management",
        onet_category="Finance",
        leadership_category="Leadership",
        skill_magnitude=65,
        market_value="Medium",
        career_equivalency="Matches Financial Coordinator",
        leadership_index=60,
        employability_score=62,
        skills_mapped=["Budget Management"],
        resume_snippet="Managed an end-to-end event budget, negotiating with 5 vendors "
        "to stay within a fixed spending limit.",
    ),
    dict(
        input_activity="Tutored neighborhood children in mathematics twice a week",
        mapped_skill="Instruction & Mentoring",
        onet_category="Education",
        leadership_category="Communication",
        skill_magnitude=58,
        market_value="Medium",
        career_equivalency="Matches Tutor / Instructional Aide",
        leadership_index=45,
        employability_score=55,
        skills_mapped=["Instruction & Mentoring"],
        resume_snippet="Delivered weekly mathematics tutoring sessions for 6 students, "
        "tracking progress and adapting lesson plans to individual needs.",
    ),
]


def seed():
    db.init_db()

    existing = db.get_user_by_username(DEMO_USERNAME)
    if existing:
        print(f"Demo user '{DEMO_USERNAME}' already exists (id={existing['id']}) — skipping seed.")
        return

    user_id = db.create_user(DEMO_USERNAME, generate_password_hash(DEMO_PASSWORD))
    print(f"Created demo user '{DEMO_USERNAME}' (id={user_id}).")

    for activity in DEMO_ACTIVITIES:
        db.insert_activity(user_id=str(user_id), **activity)
    print(f"Seeded {len(DEMO_ACTIVITIES)} demo activities.")

    db.set_user_target_role(str(user_id), "Data Scientist")
    print("Set demo target role to 'Data Scientist'.")

    print(f"\nDone. Log in with username='{DEMO_USERNAME}', password='{DEMO_PASSWORD}'.")
    print("Change this password immediately if this is anything other than a local demo.")


if __name__ == "__main__":
    seed()
