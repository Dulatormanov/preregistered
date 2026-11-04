"""The worker: the champion guesses the queued issues, one message at a time, as triage_agent.

It writes only through functions (db/004_functions.sql and db/006_revoke.sql), and runs inside each tick.
- The circuit breaker: if provider errors were saved in the last 60 minutes, one small probe call decides
  whether this run claims anything at all, so an outage adds no reads to waiting messages.
- The model call never runs inside an open database transaction (the connection is in autocommit mode),
  and complete() runs only after the model answered.
- A refusal or an invalid answer completes the message with no guess. An error goes to record_failure(),
  and the message comes back after its visibility timeout. An issue that was deleted, hidden or edited
  since first sight completes as 'gone', with a 'skipped' step.
"""
import os
import time
import urllib.error

import anthropic
from psycopg.types.json import Jsonb

from agents import champion
from notary.canonical import content_sha256

VT = 120  # seconds a claimed message stays hidden: if the worker dies, the message comes back after this
MAX_CALLS = 10  # model calls per run
BUDGET_S = 120  # no new call after this many seconds: the job's limit is 5 minutes
DAILY_CAP_USD = 3  # note: the live cap; spend_today() sums the steps of job 'tick'
OUTCOME = {"ok": "guessed", "refused": "refused", "invalid": "invalid"}  # step status -> complete() outcome


def run(db, read_issue, listed, cfg, client=None):
    """Guess queued issues until the queue is empty, or a limit or an error stops the run.

    read_issue(number) returns the issue from GitHub, or raises urllib.error.HTTPError.
    listed holds the issues this tick already read, by number, so they are not read again.
    """
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY is not set")
        client = anthropic.Anthropic(max_retries=0, timeout=60)  # note: the next tick is the retry
    n = {"guessed": 0, "refused": 0, "invalid": 0, "errors": 0, "gone": 0, "unreachable": 0, "capped": False,
         "out_of_time": False, "breaker": "closed", "cost_usd": 0.0}
    if db.execute("select prereg.spend_today('tick')").fetchone()[0] >= DAILY_CAP_USD:  # the cap covers the probe too
        n["capped"] = True
        return n
    if db.execute("select prereg.recent_provider_failures()").fetchone()[0]:
        step = champion.probe(cfg, client)
        db.execute("select prereg.record_probe(%s)", [Jsonb(step)])
        n["cost_usd"] = float(step["cost_usd"])
        if step["status"] != "ok":
            n.update(breaker="open", errors=1)
            return n
        n["breaker"] = "probe_ok"
    t0, calls, run_id = time.monotonic(), 0, os.environ.get("GITHUB_RUN_ID", "local")
    while calls < MAX_CALLS:
        if time.monotonic() - t0 > BUDGET_S:
            n["out_of_time"] = True
            break
        if db.execute("select prereg.spend_today('tick')").fetchone()[0] >= DAILY_CAP_USD:
            n["capped"] = True
            break
        row = db.execute("select * from prereg.claim_next(%s, %s)", [VT, run_id]).fetchone()
        if row is None:
            break
        attempt, _, number, _, _, seen_sha256 = row
        it = listed.get(number)
        if it is None:  # the ledger keeps no issue text, so a retry reads the issue again
            try:
                it = read_issue(number)
            except urllib.error.HTTPError as e:
                if e.code not in (404, 410):
                    n["unreachable"] += 1  # GitHub trouble: the message comes back after VT
                    break
                it = None
                reason = f"HTTPError {e.code}"  # deleted or hidden
            except Exception:  # timeouts and broken replies: the message comes back after VT
                n["unreachable"] += 1
                break
        if it is not None and content_sha256(it["title"], it["body"]) != seen_sha256:
            reason = "edited after first sight"  # guess only the text the job first saw
            it = None
        if it is None:
            db.execute("select prereg.complete(%s, 'gone', null, null, null, %s)",
                       [attempt, Jsonb(champion.new_step(cfg, "skipped", reason))])
            n["gone"] += 1
            continue
        calls += 1
        area, needs_details, h, step = champion.guess(cfg, client, it["title"], it["body"])
        n["cost_usd"] = round(n["cost_usd"] + float(step["cost_usd"]), 6)
        if step["status"] == "error":  # stop claiming: the breaker decides the next run
            db.execute("select prereg.record_failure(%s, %s)", [attempt, Jsonb(step)])
            n["errors"] += 1
            break
        db.execute("select prereg.complete(%s, %s, %s, %s, %s, %s)",
                   [attempt, OUTCOME[step["status"]], area, needs_details, h, Jsonb(step)])
        n[OUTCOME[step["status"]]] += 1
    return n
