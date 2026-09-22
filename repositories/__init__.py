"""
repositories/
=============
Repository pattern layer (Task 3 of the production-readiness pass).

Each repository class here wraps db.py's existing functions behind a clean,
class-based interface — it does NOT reimplement persistence. db.py remains
the single source of truth for actual SQL; these classes exist so:

  1. Flask routes can depend on a narrow, typed interface instead of calling
     db.* functions directly, which makes routes easier to test (swap in a
     fake repository) and easier to read (UserRepository.get_by_id(...) vs.
     db.get_user_by_id(...) scattered everywhere).
  2. If/when the SQLite-backed db.py is ever replaced with a SQLAlchemy
     implementation (see docs/ARCHITECTURE.md for why that migration wasn't
     done wholesale in this pass), only these repository classes need new
     implementations — nothing that depends on them has to change.

SCOPE NOTE: app.py's ~80 existing db.* call sites were NOT all migrated to
these repositories in this pass — that would touch nearly every route in a
2,300-line file with real regression risk, contradicting the brief's own
top priority ("preserve all functionality"). Instead, a handful of
representative routes were migrated to prove the pattern end-to-end (see
docs/ARCHITECTURE.md), and these repositories are the recommended pattern
for all new routes going forward.
"""
