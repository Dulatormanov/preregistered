"""The kill test: kill -9 the worker in the middle of a batch; nothing is half saved, and nothing twice.

Run on the test database after tests/setup_test_db.py:
  PREREG_TEST_ADMIN_URL=... python tests/test_rollback.py
It empties the ledger and the queues, queues 10 issues, and runs the real worker in a child process whose fake
Claude kills that process with SIGKILL during the 3rd model call, so no cleanup code can run. Then it checks
the four rules of the plan (Day 5).
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import psycopg  # noqa: E402
from setup_test_db import admin_url, role_url  # noqa: E402
from test_tick import look, reset  # noqa: E402

from agents import champion  # noqa: E402
from notary.canonical import content_sha256  # noqa: E402
from runner import worker  # noqa: E402

ISSUES = {n: {"number": n, "title": f"Login fails, case {n}", "body": f"Steps for case {n}."} for n in range(7001, 7011)}


class FakeClaude:
    def __init__(self, kill_at=None):
        self.calls, self.kill_at, self.messages = 0, kill_at, self

    def create(self, **kw):
        self.calls += 1
        if self.calls == self.kill_at:
            os.kill(os.getpid(), signal.SIGKILL)  # kill -9 during the model call: no cleanup runs
        r = NS(stop_reason="end_turn", content=[NS(type="text", text='{"area": "auth", "needs_details": false}')],
               usage=NS(input_tokens=1000, output_tokens=16, cache_read_input_tokens=0, cache_creation_input_tokens=0))
        r._request_id = "req_kill_test"
        return r


def run_worker(kill_at=None):
    worker.VT = 1  # a claimed message comes back after 1 second in this test
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as db:
        return worker.run(db, ISSUES.__getitem__, ISSUES, champion.load(), client=FakeClaude(kill_at))


def main():
    if sys.argv[1:] == ["--child"]:
        run_worker(kill_at=3)
        raise SystemExit("the worker was not killed")
    reset()
    champion_id = champion.load()["c"]["id"]
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:
        for n, it in ISSUES.items():  # no baseline guess here: every guess below is the champion's
            assert t.execute("select prereg.enqueue_issue(%s, now(), %s, '{}', %s, null)",
                             [n, content_sha256(it["title"], it["body"]), champion_id]).fetchone()[0]
    child = subprocess.run([sys.executable, __file__, "--child"], env=os.environ)
    assert child.returncode == -signal.SIGKILL, child.returncode

    # 1. no half-written guess and no duplicate: each guess has exactly one step and one 'finished' event
    guessed = look("select issue_number, count(*) from prereg.predictions group by 1 order by 1")
    assert [c for _, c in guessed] == [1, 1], guessed
    assert look("select count(*) from prereg.steps")[0][0] == 2
    assert sorted(n for n, _ in guessed) == sorted(int(n) for (n,) in look(
        "select data->>'issue_number' from prereg.run_events where kind = 'finished'"))
    print("ok 1: killed during the 3rd call: 2 guesses, each with one step and one finished event")

    # 2. every unfinished message is back in the queue after its visibility timeout
    time.sleep(1.2)
    assert look("select count(*) from pgmq.q_triage_events where vt <= now()")[0][0] == 8
    print("ok 2: the 8 unfinished messages are back in the queue after the timeout")

    # 3. a rerun leaves exactly 10 guesses
    n = run_worker()
    assert n["guessed"] == 8 and look("select count(*), count(distinct issue_number) from prereg.predictions") == [(10, 10)]
    print("ok 3: a rerun guesses the other 8: exactly 10 guesses, one per issue")

    # 4. the sweep gives the killed attempt one 'abandoned' event
    time.sleep(1.1)
    look("select prereg.sweep_abandoned('1 second')")
    killed = look("select r.id from prereg.runs r where not exists (select from prereg.run_events e"
                  " where e.kind in ('finished', 'failed') and e.data->>'attempt_id' = r.id::text)")
    assert len(killed) == 1, killed
    assert look("select count(*) from prereg.run_events where kind = 'abandoned' and data->>'attempt_id' = %s",
                str(killed[0][0]))[0][0] == 1
    print("ok 4: the killed attempt has exactly one abandoned event")


if __name__ == "__main__":
    main()
