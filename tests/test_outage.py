"""A fake 3-hour provider outage (Build day 7): 12 ticks while every model call fails. The circuit breaker must keep
every waiting message unread but once at most, send nothing to triage_dlq, and let every issue be guessed after it.

  PREREG_TEST_ADMIN_URL=... python tests/test_outage.py
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import anthropic
import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url, role_url  # noqa: E402
from agents import champion  # noqa: E402
from runner import worker  # noqa: E402
from notary.canonical import content_sha256  # noqa: E402

DOWN = [True]
ISSUES = {n: {"number": n, "title": f"Issue {n}", "body": f"body {n}"} for n in range(9401, 9406)}


class Claude:
    def __init__(self):
        self.messages, self.calls = self, 0

    def create(self, **kw):
        self.calls += 1
        if DOWN[0]:
            e = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
            e.__dict__.update(status_code=529, request_id="req_down")
            raise e
        r = NS(stop_reason="end_turn", content=[NS(type="text", text='{"area": "other", "needs_details": false}')],
               usage=NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0))
        r._request_id = "req_ok"
        return r


def look(sql):
    with psycopg.connect(admin_url(), autocommit=True) as a:
        return a.execute(sql).fetchall()


def main():
    with psycopg.connect(admin_url(), autocommit=True) as a:
        a.execute("select pgmq.purge_queue('triage_events'), pgmq.purge_queue('triage_dlq')")
        a.execute("set role prereg_owner")
        a.execute("truncate prereg.outcomes, prereg.runs, prereg.steps, prereg.run_events, prereg.anchors,"
                  " prereg.predictions, prereg.issues_seen restart identity")
    cfg = champion.load()
    worker.VT = 1
    claude = Claude()
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as db:
        for n, it in ISSUES.items():
            db.execute("select prereg.enqueue_issue(%s, now(), %s, '{}', %s, null)",
                       [n, content_sha256(it["title"], it["body"]), cfg["c"]["id"]])
        for _ in range(12):  # 12 ticks: 3 hours of 15-minute slots
            worker.run(db, ISSUES.__getitem__, {}, cfg, client=claude)
            time.sleep(1.1)  # past the 1-second visibility timeout
        during = claude.calls
        waiting = look("select max(read_ct), count(*) from pgmq.q_triage_events")[0]
        dead = look("select count(*) from pgmq.q_triage_dlq")[0][0]
        DOWN[0] = False
        result = worker.run(db, ISSUES.__getitem__, {}, cfg, client=claude)
    assert dead == 0, dead
    assert waiting[0] <= 1 and waiting[1] == 5, waiting  # all 5 still waiting, and none read more than once
    assert during == 12, during  # the first tick's one call, then one probe a tick: no message is claimed
    assert result["guessed"] == 5 and result["breaker"] == "probe_ok", result
    assert look("select count(*) from prereg.predictions where champion_id <> 'rules_v0'")[0][0] == 5
    print(f"ok: a 3-hour outage left 0 dead letters, read no waiting message more than once ({during} calls in 12"
          " ticks), and every issue was guessed after it")


if __name__ == "__main__":
    main()
