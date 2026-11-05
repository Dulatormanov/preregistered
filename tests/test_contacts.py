"""The contact budget and the redrive (db/014_contacts.sql) on the test database: 50 sends at once land once, each
kind keeps its own window, and a dead letter goes back into the queue once, with a logged event.

  PREREG_TEST_ADMIN_URL=... python tests/test_contacts.py
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url, role_url  # noqa: E402


def send(kind, topic=""):
    """One send as its own session, as the owner: notifier may hold only 2 sessions, and the race is the point."""
    with psycopg.connect(admin_url(), autocommit=True) as c:
        c.execute("set role prereg_owner")
        try:
            c.execute("select prereg.spend_contact(%s, %s)", [kind, topic])
            return True
        except psycopg.errors.UniqueViolation:
            return False


def main():
    with ThreadPoolExecutor(50) as pool:
        landed = list(pool.map(lambda _: send("weekly_report"), range(50)))
    assert landed.count(True) == 1, landed.count(True)  # 50 sends at once: one weekly report
    with psycopg.connect(role_url("notifier"), autocommit=True) as n:
        try:
            n.execute("select prereg.spend_contact('weekly_report', '')")
            raise AssertionError("a second weekly report in the same week")
        except psycopg.errors.UniqueViolation as e:
            assert e.sqlstate == "23505"
        n.execute("select prereg.spend_contact('alert', 'Watchdog: missed:tick/poll')")
        n.execute("select prereg.spend_contact('alert', 'Watchdog: dead_letters')")  # another type: its own window
        n.execute("select prereg.spend_contact('approval_request', '')")  # the day's one approval request
        for again in (("alert", "Watchdog: missed:tick/poll"), ("approval_request", "")):  # a second, in its window
            try:
                n.execute("select prereg.spend_contact(%s, %s)", list(again))
                raise AssertionError(f"a second {again} in its window")
            except psycopg.errors.UniqueViolation:
                pass
        try:
            n.execute("select count(*) from prereg.contacts")
            raise AssertionError("notifier read a table")
        except psycopg.errors.InsufficientPrivilege:
            pass

    # The redrive: a poison message reaches triage_dlq, then goes back to the queue once.
    with psycopg.connect(admin_url(), autocommit=True) as a:
        a.execute("select pgmq.purge_queue('triage_events'), pgmq.purge_queue('triage_dlq')")
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:
        t.execute("select prereg.enqueue_issue(9501, now(), 'h', '{}', 'haiku55-p2', null)")
        for _ in range(6):  # read 6 times without finishing: the 6th read makes it a dead letter
            t.execute("select * from prereg.claim_next(1, 'test')").fetchone()
            time.sleep(1.1)
    with psycopg.connect(admin_url(), autocommit=True) as a:
        (dead,) = a.execute("select msg_id from pgmq.q_triage_dlq").fetchone()
    with psycopg.connect(role_url("redriver"), autocommit=True) as r:
        assert r.execute("select prereg.redrive_dlq(%s)", [dead]).fetchone()[0] is True
        assert r.execute("select prereg.redrive_dlq(%s)", [dead]).fetchone()[0] is False  # gone from the dead letters
        assert r.execute("select * from prereg.queue_health()").fetchone()[0] == 0
    with psycopg.connect(admin_url(), autocommit=True) as a:
        assert a.execute("select count(*) from pgmq.q_triage_events where message->>'issue_number' = '9501'"
                         ).fetchone()[0] == 1
        a.execute("set role prereg_owner")
        assert a.execute("select count(*) from prereg.run_events where kind = 'redriven'").fetchone()[0] == 1
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:  # leave the queue empty for later tests
        attempt = t.execute("select * from prereg.claim_next(30, 'test')").fetchone()[0]
        t.execute("select prereg.complete(%s, 'gone', null, null, null, %s)", [attempt, Jsonb(
            {"champion_id": "haiku55-p2", "model": "claude-haiku-5-5", "status": "skipped", "lock_sha256": "x"})])
    print("ok: 50 sends at once land once (23505 for the rest), each window holds, and a redrive happens once")


if __name__ == "__main__":
    main()
