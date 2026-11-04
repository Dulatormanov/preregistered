"""The queue and its functions, on the test database only (see tests/setup_test_db.py).

  PREREG_TEST_ADMIN_URL=... python tests/test_db_functions.py
Every call is made as the job role that will make it from Day 5 on; the admin login only looks.
"""
import sys
import time
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_test_db import admin_url, role_url  # noqa: E402

STEP = {"champion_id": "haiku55-p0", "model": "claude-haiku-5-5", "status": "ok", "request_id": "req_test",
        "input_tokens": 1000, "output_tokens": 16, "cache_read_tokens": 0, "cache_write_tokens": 0,
        "cost_usd": 0.000108, "lock_sha256": "x" * 64, "error": None}
BASELINE = {"champion_id": "rules_v0", "area": "other", "needs_details": False, "input_sha256": "h"}


def look(sql, *args):  # read-only, as the table owner
    with psycopg.connect(admin_url(), autocommit=True) as c:
        c.execute("set role prereg_owner")
        return c.execute(sql, args).fetchall()


def job(role="triage_agent"):
    return psycopg.connect(role_url(role), autocommit=True)


def enqueue(c, n, baseline=BASELINE):
    return c.execute("select prereg.enqueue_issue(%s, now(), 'h', %s, 'haiku55-p0', %s)",
                     [n, ["bug"], Jsonb(baseline) if baseline else None]).fetchone()[0]


def claim(c, vt=30):
    return c.execute("select * from prereg.claim_next(%s, 'test-run')", [vt]).fetchone()


def complete(c, attempt, outcome, area=None, needs_details=None, step=STEP):
    return c.execute("select prereg.complete(%s, %s, %s, %s, 'h', %s)",
                     [attempt, outcome, area, needs_details, Jsonb(step) if step else None]).fetchone()[0]


def denied(c, sql, *args):
    try:
        c.execute(sql, args)
    except psycopg.errors.InsufficientPrivilege:
        return True
    return False


def test_first_sight_guess_and_a_repeated_complete():
    with job() as t:
        assert enqueue(t, 9001) is True and enqueue(t, 9001) is False  # first sight happens once
        attempt, _, issue, champion, read_ct = claim(t)
        assert (issue, champion, read_ct) == (9001, "haiku55-p0", 1)
        assert complete(t, attempt, "guessed", "auth", False) == "done"
        assert complete(t, attempt, "guessed", "auth", False) == "already_done"  # a repeated call does nothing
        assert claim(t) is None
    assert look("select champion_id, area from prereg.predictions where issue_number = 9001 order by id") == [
        ("rules_v0", "other"), ("haiku55-p0", "auth")]
    assert look("select count(*) from prereg.steps where issue_number = 9001")[0][0] == 1
    assert look("select count(*) from prereg.run_events where kind = 'finished' and data->>'attempt_id' = %s",
                str(attempt))[0][0] == 1


def test_a_gone_issue_finishes_without_a_guess():
    with job() as t:
        enqueue(t, 9002)
        attempt = claim(t)[0]
        assert complete(t, attempt, "gone", step=dict(STEP, status="skipped", error="HTTPError 410")) == "done"
    assert look("select count(*) from prereg.predictions where issue_number = 9002 and champion_id = 'haiku55-p0'"
                )[0][0] == 0
    assert look("select data->>'outcome' from prereg.run_events where kind = 'finished'"
                " and data->>'issue_number' = '9002'") == [("gone",)]


def test_a_poison_message_goes_to_the_dead_letter_queue_on_its_6th_read():
    with job() as t:
        enqueue(t, 9003)
        for read in range(1, 6):
            attempt, _, issue, _, read_ct = claim(t, vt=1)
            assert (issue, read_ct) == (9003, read)
            t.execute("select prereg.record_failure(%s, %s)", [attempt, Jsonb(dict(STEP, error="APIStatusError 529"))])
            time.sleep(1.2)  # past the 1-second visibility timeout
        assert claim(t, vt=1) is None  # the 6th read moves it to triage_dlq instead
        assert t.execute("select prereg.recent_provider_failures()").fetchone()[0] >= 5
    assert look("select count(*) from pgmq.q_triage_dlq where message->>'issue_number' = '9003'")[0][0] == 1
    assert look("select count(*) from pgmq.q_triage_events where message->>'issue_number' = '9003'")[0][0] == 0
    assert look("select data->>'read_ct' from prereg.run_events where kind = 'dead_letter'") == [("6",)]


def test_a_temporary_table_cannot_stand_in_for_the_ledger():
    with job() as t:
        for table in ("predictions", "steps", "run_events", "runs", "issues_seen"):
            t.execute(f"create temporary table {table} (issue_number int)")
        enqueue(t, 9004)
        attempt = claim(t)[0]
        assert complete(t, attempt, "guessed", "postgres", True) == "done"
        assert t.execute("select count(*) from pg_temp.predictions").fetchone()[0] == 0
    assert look("select area from prereg.predictions where issue_number = 9004 and champion_id = 'haiku55-p0'") == [
        ("postgres",)]


def test_log_event_writes_polled_events_only():
    with job() as t:
        assert denied(t, "select prereg.log_event('finished', '{}')")
        t.execute("select prereg.log_event('polled', '{\"test\": true}')")


def test_the_sweep_marks_an_attempt_that_never_finished():
    with job() as t:
        enqueue(t, 9005)
        attempt = claim(t)[0]  # the job dies here: no complete, no failure
    assert look("select prereg.sweep_abandoned('0 seconds')")[0][0] == 1
    assert look("select prereg.sweep_abandoned('0 seconds')")[0][0] == 0  # marked once only
    assert look("select count(*) from prereg.run_events where kind = 'abandoned' and data->>'attempt_id' = %s",
                str(attempt))[0][0] == 1


def test_an_outcome_is_saved_once_and_only_through_record_outcome():
    with job("collector") as k, job() as t:
        add = "select prereg.record_outcome(9001, %s, 'studio', 'add', 'User', false, now())"
        assert k.execute(add, ["event-1"]).fetchone()[0] is True
        assert k.execute(add, ["event-1"]).fetchone()[0] is None  # the same GitHub event again: not saved twice
        assert denied(k, "insert into prereg.outcomes (issue_number, event_key, label, action, actor, by_author,"
                         " labeled_at) values (9001, 'x', 'x', 'add', 'User', false, now())")
        assert denied(t, add, "event-2")
    assert look("select count(*) from prereg.outcomes where issue_number = 9001")[0][0] == 1


def test_each_job_calls_only_its_own_functions():
    with job("notary") as n, job("observer") as o, job() as t:
        assert denied(n, "select * from prereg.claim_next(1, 'x')")
        assert denied(o, "select prereg.complete(1, 'gone', null, null, null, null)")
        assert denied(t, "select prereg.record_anchor('x', 'x', 1, 1, now())")
        assert denied(t, "select prereg.sweep_abandoned('0 seconds')")
        assert denied(t, "select * from pgmq.read('triage_events', 1, 1)")  # no way around the functions


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print("ok", name)
