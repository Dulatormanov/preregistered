"""The drift check (ops/drift.py) on the test database: clean after the migrations, and it alerts on a changed
function and on an extra grant. Run it last: it changes the database, then puts it back.

  PREREG_TEST_ADMIN_URL=... python tests/test_drift.py
"""
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url, role_url  # noqa: E402
from ops.drift import check  # noqa: E402


def as_observer():
    with psycopg.connect(role_url("observer"), autocommit=True) as o:
        return check(o)


def main():
    assert as_observer() == {}, as_observer()
    with psycopg.connect(admin_url(), autocommit=True) as a:
        a.execute("set role prereg_owner")
        original = a.execute("select pg_get_functiondef('prereg.spend_total(text)'::regprocedure)").fetchone()[0]
        a.execute("create or replace function prereg.spend_total(p_job text) returns numeric language sql stable"
                  " security definer set search_path = pg_catalog, pg_temp as $$ select 0::numeric $$")
        a.execute("grant execute on function prereg.queue_health() to triage_agent")
        try:
            alerts = as_observer()
            assert "spend_total" in alerts.get("functions", ""), alerts
            assert "extra triage_agent EXECUTE queue_health" in alerts.get("privileges", ""), alerts
        finally:
            a.execute(original)
            a.execute("revoke execute on function prereg.queue_health() from triage_agent")
    assert as_observer() == {}
    print("ok: the drift check is clean on the migrations, and alerts on a changed function and an extra grant")


if __name__ == "__main__":
    main()
