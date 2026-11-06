"""The worker: the champion guesses the queued issues, one message at a time, as triage_agent.

It writes only through functions (db/004_functions.sql and db/006_revoke.sql), and runs inside each tick.
- The circuit breaker: if provider errors were saved in the last 60 minutes, one small probe call decides
  whether this run claims anything at all, so an outage adds no reads to waiting messages.
- The model call never runs inside an open database transaction (the connection is in autocommit mode),
  and complete() runs only after the model answered.
- A refusal or an invalid answer completes the message with no guess. An error goes to record_failure(),
  which puts the message back with a fresh read count, so provider errors are retried for 24 hours.
- An issue that was deleted, hidden or edited since first sight completes as 'gone', with a 'skipped' step.
- A message queued for another champion gets no call: the guess that counts belongs to the champion
  models.lock named at first sight. It comes back after its visibility timeout.
- A failed GitHub read moves on to the next message (at most MAX_READ_FAILURES per run); the message comes
  back after its visibility timeout, and on its 6th read it becomes a dead letter, which fails the tick.
"""
import os
import time
import urllib.error

import anthropic
from psycopg.types.json import Jsonb

from agents import champion
from core import models
from notary.canonical import content_sha256

VT = 120  # seconds a claimed message stays hidden: if the worker dies, the message comes back after this
MAX_CALLS = 10  # model calls per run, the probe included
MAX_READ_FAILURES = 3  # failed GitHub reads per run
BUDGET_S = 120  # no new call after this many seconds: the job's limit is 5 minutes
OUTCOME = {"ok": "guessed", "refused": "refused", "invalid": "invalid"}  # step status -> complete() outcome


def over_cap(db):
    used, cap = models.spent(db, "tick")
    return used >= cap


def run(db, read_issue, listed, cfg, client=None):
    """Guess queued issues until the queue is empty, or a limit or an error stops the run.

    read_issue(number) returns the issue from GitHub, or raises urllib.error.HTTPError.
    listed holds the issues this tick already read, by number, so they are not read again.
    """
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY is not set")
        client = anthropic.Anthropic(base_url="http://127.0.0.1:9", max_retries=0, timeout=60)  # GD2 (GAME_DAYS.md): the provider unreachable; never merged
    t0, calls, run_id = time.monotonic(), 0, os.environ.get("GITHUB_RUN_ID", "local")  # the probe counts too
    n = {"guessed": 0, "refused": 0, "invalid": 0, "errors": 0, "gone": 0, "unreachable": 0, "other_champion": 0,
         "capped": False, "out_of_time": False, "breaker": "closed", "cost_usd": 0.0}
    if over_cap(db):  # the cap covers the probe too
        n["capped"] = True
        return n
    if db.execute("select prereg.recent_provider_failures()").fetchone()[0]:
        try:
            step = models.probe(db, "tick", cfg, client)
        except models.OverCap:
            n["capped"] = True
            return n
        calls += 1
        db.execute("select prereg.record_probe(%s)", [Jsonb(step)])
        n["cost_usd"] = float(step["cost_usd"])
        if step["status"] != "ok":
            n.update(breaker="open", errors=1)
            return n
        n["breaker"] = "probe_ok"
    while calls < MAX_CALLS:
        if time.monotonic() - t0 > BUDGET_S:
            n["out_of_time"] = True
            break
        if over_cap(db):  # checked before a claim, so a capped run takes no message
            n["capped"] = True
            break
        row = db.execute("select * from prereg.claim_next(%s, %s)", [VT, run_id]).fetchone()
        if row is None:
            break
        attempt, _, number, queued_champion, _, seen_sha256 = row
        if queued_champion != cfg["c"]["id"]:  # no call: the message comes back after VT
            n["other_champion"] += 1
            continue
        it = listed.get(number)
        if it is None:  # the ledger keeps no issue text, so a retry reads the issue again
            try:
                it = read_issue(number)
            except urllib.error.HTTPError as e:
                if e.code not in (404, 410):  # GitHub trouble: the message comes back after VT
                    n["unreachable"] += 1
                    if n["unreachable"] >= MAX_READ_FAILURES:
                        break
                    continue
                it = None
                reason = f"HTTPError {e.code}"  # deleted or hidden
            except Exception:  # timeouts and broken replies: the message comes back after VT
                n["unreachable"] += 1
                if n["unreachable"] >= MAX_READ_FAILURES:
                    break
                continue
        if it is not None and content_sha256(it["title"], it["body"]) != seen_sha256:
            reason = "edited after first sight"  # guess only the text the job first saw
            it = None
        if it is None:
            db.execute("select prereg.complete(%s, 'gone', null, null, null, %s)",
                       [attempt, Jsonb(champion.new_step(cfg, "skipped", reason))])
            n["gone"] += 1
            continue
        try:  # only the title and the body go to the model
            area, needs_details, h, step = models.answer(db, "tick", cfg, client, it["title"], it["body"])
        except models.OverCap:  # the cap was reached since the check above: the message comes back after VT
            n["capped"] = True
            break
        calls += 1
        n["cost_usd"] = round(n["cost_usd"] + float(step["cost_usd"]), 6)
        if step["status"] == "error":  # stop claiming: the breaker decides the next run
            db.execute("select prereg.record_failure(%s, %s)", [attempt, Jsonb(step)])
            n["errors"] += 1
            break
        db.execute("select prereg.complete(%s, %s, %s, %s, %s, %s)",
                   [attempt, OUTCOME[step["status"]], area, needs_details, h, Jsonb(step)])
        n[OUTCOME[step["status"]]] += 1
    return n
