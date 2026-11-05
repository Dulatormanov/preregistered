"""The contact budget, from the job's side (Build day 7, ADR-008): every message to a person spends from
prereg.contacts first. One weekly report a week, one approval request a day, one comment per alert type per 6 hours.

  spend(kind, topic) -> True if the budget allows this message now, False if its window is already spent.
The window is the database's own unique key, so two jobs at once cannot both spend it.
"""
import os


def spend(kind, topic=""):
    import psycopg
    with psycopg.connect(os.environ["NOTIFIER_DB_URL"], autocommit=True) as db:  # notifier: spend_contact only
        try:
            db.execute("select prereg.spend_contact(%s, %s)", [kind, topic])
            return True
        except psycopg.errors.UniqueViolation:
            return False
