"""One tick: read new upstream issues, queue each first sight with its baseline guess, run the worker.

Prints counts only, never issue numbers or text: Actions logs are public.
The job logs in as triage_agent, which holds no table right: every read and write is a function call
(db/004_functions.sql, db/006_revoke.sql). The connection is in autocommit mode, so no transaction is open
during a network call (the role's idle-in-transaction timeout is 30 seconds).
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.types.json import Jsonb

from agents import champion, rules_v0
from notary.canonical import content_sha256
from runner import worker

UPSTREAM = "https://api.github.com/repos/supabase/supabase/issues"
START = datetime(2026, 11, 3, tzinfo=timezone.utc)  # first day of the ledger, see DECISIONS.md
OVERLAP = timedelta(hours=1)  # re-read the last hour; first sight is decided by the primary key
PER_PAGE = 30  # a full page of 100 is about 0.5 MB of issue bodies
MAX_PAGES = 20  # note: 600 issues and PRs, days of missed ticks; page further if that ever runs out


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def planned_slot(now):
    """The slot this run was planned for. tick.yml has one cron line per slot, and passes it as SCHEDULE."""
    m = int((os.environ.get("SCHEDULE") or str(now.minute)).split()[0])  # workflow_dispatch: its own start
    t = now.replace(minute=m, second=0, microsecond=0)
    return t if t <= now else t - timedelta(hours=1)  # note: right for delays under 60 minutes


def github(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "preregistered"})
    with urllib.request.urlopen(req, timeout=30) as r:  # note: urllib follows a 301 (a moved issue)
        return r.status, json.load(r), r.headers


def new_issues(token, cutoff, event):
    """Issues (not PRs) created at or after cutoff, newest first."""
    out = []
    for page in range(1, MAX_PAGES + 1):
        event["http_status"], batch, headers = github(
            f"{UPSTREAM}?state=all&sort=created&direction=desc&per_page={PER_PAGE}&page={page}", token)
        event.setdefault("token_expires", headers.get("github-authentication-token-expiration"))  # Check 9
        for it in batch:
            if "pull_request" in it:
                continue
            event.setdefault("newest_upstream", it["number"])
            if utc(it["created_at"]) < cutoff:
                return out
            out.append(it)
        if len(batch) < PER_PAGE:
            return out
    return out


def main():
    started = datetime.now(timezone.utc)
    event = {"trigger": os.environ.get("GITHUB_EVENT_NAME"), "run_id": os.environ.get("GITHUB_RUN_ID"),
             "planned_start": planned_slot(started).isoformat(), "actual_start": started.isoformat()}
    token = os.environ["PREREG_READ_TOKEN"]
    cfg = champion.load()  # the champion named in models.lock goes into each queued message
    with psycopg.connect(os.environ["TRIAGE_DB_URL"], autocommit=True) as db:
        newest = db.execute("select prereg.newest_first_sight()").fetchone()[0]
        cutoff = max(START, newest - OVERLAP) if newest else START
        try:
            issues = new_issues(token, cutoff, event)
        except Exception as e:  # record the failure, then fail the job loudly
            event.update(http_status=getattr(e, "code", None), error=type(e).__name__)
            db.execute("select prereg.log_event('polled', %s)", [Jsonb(event)])
            raise
        saved = 0
        # All or nothing: the next cutoff comes from the newest first sight, so saving only the newest
        # issues of a crashed tick would skip the older ones for good. The loop makes no network call.
        with db.transaction():
            for it in issues:
                h = content_sha256(it["title"], it["body"])
                area, needs_details = rules_v0.guess(it["title"], it["body"])
                saved += db.execute(
                    "select prereg.enqueue_issue(%s, %s, %s, %s, %s, %s)",
                    [it["number"], utc(it["created_at"]), h, [label["name"] for label in it["labels"]],
                     cfg["c"]["id"], Jsonb({"area": area, "needs_details": needs_details, "input_sha256": h})],
                ).fetchone()[0]
        failure = None
        try:
            n = worker.run(db, lambda number: github(f"{UPSTREAM}/{number}", token)[1],
                           {it["number"]: it for it in issues}, cfg)
        except BaseException as e:  # record the run and its outputs first, then fail loudly
            n, failure = {"error": type(e).__name__}, e
        pending = db.execute("select prereg.unanchored_guesses()").fetchone()[0]
        event.update(issues=len(issues), saved=saved, pending=pending, champion=n)
        db.execute("select prereg.log_event('polled', %s)", [Jsonb(event)])
    anchor = "yes" if pending or os.environ.get("ANCHOR_FILE", "").strip() else "no"
    print(f"polled http={event.get('http_status')} issues={len(issues)} saved={saved} pending={pending}"
          f" champion: {' '.join(f'{k}={v}' for k, v in n.items())}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"pending={pending}\nanchor={anchor}\n")
    if failure:
        raise failure
    if n["errors"] and not (n["guessed"] or n["refused"] or n["invalid"]):  # no call got any answer
        sys.exit("the champion got no answer: check the Anthropic key and status page")  # fail loudly


if __name__ == "__main__":
    main()
