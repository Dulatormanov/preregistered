"""Make a throwaway test database from Supabase's own Postgres image, the version prereg-prod runs.

  docker run -d -e POSTGRES_PASSWORD=ci-only -p 127.0.0.1:54329:5432 supabase/postgres:17.11.0.018
  PREREG_TEST_ADMIN_URL=postgresql://postgres:ci-only@127.0.0.1:54329/postgres python tests/setup_test_db.py

It applies every migration in db/ as postgres, gives the job roles the password 'test-only', and runs
check_roles.sql. It refuses any database that is not on this machine, so it can never touch prereg-prod.
"""
import os
import sys
from pathlib import Path

import psycopg

DB = Path(__file__).resolve().parents[1] / "db"
TEST_PASSWORD = "test-only"  # note: plain text is fine for a throwaway local database, never for prereg-prod


def admin_url():
    url = os.environ["PREREG_TEST_ADMIN_URL"]
    if psycopg.conninfo.conninfo_to_dict(url).get("host") not in ("localhost", "127.0.0.1"):
        sys.exit("PREREG_TEST_ADMIN_URL must point at a local test database")
    return url


def role_url(role):
    d = psycopg.conninfo.conninfo_to_dict(admin_url())
    return psycopg.conninfo.make_conninfo(**{**d, "user": role, "password": TEST_PASSWORD})


def main():
    with psycopg.connect(admin_url(), autocommit=True) as c:
        if c.execute("select to_regnamespace('prereg') is not null").fetchone()[0]:
            sys.exit("this test database already has the ledger: start a fresh container")
        for f in sorted(DB.glob("[0-9][0-9][0-9]_*.sql")):
            c.execute(f.read_text())
            print("applied", f.name)
        for role in ("triage_agent", "notary", "observer", "collector", "gate_runner", "adopter", "proposer", "gateway_svc"):
            c.execute(f"alter role {role} password '{TEST_PASSWORD}'")
        bad = [name for name, ok in c.execute((DB / "check_roles.sql").read_text()).fetchall() if not ok]
    print("check_roles:", "all true" if not bad else f"FAIL {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
