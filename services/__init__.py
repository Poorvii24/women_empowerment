"""
ISIS Career Intelligence Services
==================================
Phase 4 — production-grade career platform services, separate from the
core activity-analysis NLP pipeline (nlp/). Each module here has a single
responsibility and no Flask dependency, so each is independently testable.

Modules:
    role_taxonomy.py          – static reference data: target roles -> required skills
    resume_parser.py           – PDF/DOCX text extraction + section parsing
    skill_gap_engine.py        – embedding-based comparison: user skills vs target role
    scoring_engine.py          – 5-axis Career Readiness Score computation
    learning_recommender.py    – 30/60/90 day learning plan generator
    growth_tracker.py          – historical activity trend aggregation for charts
    opportunity_recommender.py – projects/hackathons/certifications suggestions
"""
