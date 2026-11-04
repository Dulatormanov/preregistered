"""One tick: read new upstream issues, save the baseline and the champion guesses, log a 'polled' event.

Prints counts only, never issue numbers or text: Actions logs are public.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import anthropic
import psycopg
from psycopg.types.json import Jsonb

from agents import champion, rules_v0
from notary.canonical import content_sha256

UPSTREAM = "https://api.github.com/repos/supabase/supabase/issues"
START = datetime(2026, 11, 3, tzinfo=timezone.utc)  # first day of the ledger, see DECISIONS.md
OVERLAP = timedelta(hours=1)  # re-read the last hour; first sight is decided by the primary key
PER_PAGE = 30  # a full page of 100 is about 0.5 MB of issue bodies
MAX_PAGES = 20  # note: 600 issues and PRs, days of missed ticks; page further if that ever runs out
DAILY_CAP_USD = 3  # note: the live cap lives here until spend_today() moves it into the database
MAX_CALLS = 10  # champion calls per tick
BUDGET_S = 120  # no new champion call after this many seconds: the job's limit is 5 minutes
RETRY = timedelta(hours=24)  # how long a champion call that errored is tried again
STEP = ("job", "issue_number", "champion_id", "model", "status", "request_id", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_write_tokens", "cost_usd", "lock_sha256", "error")
COUNT = {"ok": "guessed", "refused": "refused", "invalid": "invalid", "error": "errors", "skipped": "skipped"}


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
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.load(r)


def new_issues(token, cutoff, event):
    """Issues (not PRs) created at or after cutoff, newest first."""
    out = []
    for page in range(1, MAX_PAGES + 1):
        event["http_status"], batch = github(
            f"{UPSTREAM}?state=all&sort=created&direction=desc&per_page={PER_PAGE}&page={page}", token)
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


def champion_pass(db, token, listed):
    """The champion guesses each issue seen in the last day that it has not finished yet, oldest first.

    It guesses only the text the job first saw: an issue that was edited, deleted or hidden before its call
    gets a final 'skipped' step. A refused or invalid answer is final too: it is a result. An error is
    tried again on the next tick, which is the only retry.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    cfg, t0, calls = champion.load(), time.monotonic(), 0
    client = anthropic.Anthropic(max_retries=0, timeout=60)  # note: the SDK would sleep through a long retry-after
    todo = db.execute(
        "select issue_number, content_sha256 from prereg.issues_seen s where first_seen_at > now() - %s"
        " and not exists (select 1 from prereg.predictions p where p.issue_number = s.issue_number"
        "   and p.champion_id = %s and p.trial = 1)"
        " and not exists (select 1 from prereg.steps t where t.issue_number = s.issue_number"
        "   and t.champion_id = %s and t.status in ('refused', 'invalid', 'skipped'))"
        " order by issue_number", [RETRY, cfg["c"]["id"], cfg["c"]["id"]]).fetchall()
    n = {"guessed": 0, "refused": 0, "invalid": 0, "errors": 0, "skipped": 0, "unreachable": 0, "capped": False,
         "out_of_time": False, "cost_usd": 0.0}
    for number, seen_sha256 in todo:
        if calls >= MAX_CALLS:
            break
        if time.monotonic() - t0 > BUDGET_S:
            n["out_of_time"] = True
            break
        spent = db.execute("select coalesce(sum(cost_usd), 0) from prereg.steps"
                           " where job = 'tick' and created_at >= date_trunc('day', now(), 'UTC')").fetchone()[0]
        if spent >= DAILY_CAP_USD:
            n["capped"] = True
            break
        it, step = listed.get(number), None
        if it is None:  # the ledger keeps no issue text, so a retry reads the issue again
            try:  # note: urllib follows a 301 (a moved issue); the Day 3 queue treats it as gone instead
                _, it = github(f"{UPSTREAM}/{number}", token)
            except urllib.error.HTTPError as e:
                if e.code not in (404, 410):
                    n["unreachable"] += 1  # GitHub trouble: try again next tick
                    continue
                step = champion.new_step(cfg, "skipped", f"HTTPError {e.code}")  # deleted or hidden
            except Exception:  # timeouts and broken replies: try again next tick
                n["unreachable"] += 1
                continue
        if step is None and content_sha256(it["title"], it["body"]) != seen_sha256:
            step = champion.new_step(cfg, "skipped", "edited after first sight")
        area = needs_details = h = None
        if step is None:
            calls += 1
            area, needs_details, h, step = champion.guess(cfg, client, it["title"], it["body"])
        db.execute(f"insert into prereg.steps ({', '.join(STEP)}) values ({', '.join(['%s'] * len(STEP))})",
                   ["tick", number] + [step[k] for k in STEP[2:]])
        if area is not None:
            db.execute(
                "insert into prereg.predictions (issue_number, champion_id, area, needs_details, input_sha256)"
                " values (%s, %s, %s, %s, %s)", [number, cfg["c"]["id"], area, needs_details, h])
        db.commit()  # each guess is saved with its step before the next call
        n[COUNT[step["status"]]] += 1
        n["cost_usd"] = round(n["cost_usd"] + float(step["cost_usd"]), 6)
    return n


def main():
    started = datetime.now(timezone.utc)
    event = {"trigger": os.environ.get("GITHUB_EVENT_NAME"), "run_id": os.environ.get("GITHUB_RUN_ID"),
             "planned_start": planned_slot(started).isoformat(), "actual_start": started.isoformat()}
    token = os.environ["PREREG_READ_TOKEN"]
    with psycopg.connect(os.environ["TRIAGE_DB_URL"]) as db:
        newest = db.execute("select max(gh_created_at) from prereg.issues_seen").fetchone()[0]
        cutoff = max(START, newest - OVERLAP) if newest else START
        try:
            issues = new_issues(token, cutoff, event)
        except Exception as e:  # record the failure, then fail the job loudly
            event.update(http_status=getattr(e, "code", None), error=type(e).__name__)
            db.execute("insert into prereg.run_events (kind, data) values ('polled', %s)", [Jsonb(event)])
            db.commit()
            raise
        saved = 0
        for it in issues:
            h = content_sha256(it["title"], it["body"])
            first_sight = db.execute(
                "insert into prereg.issues_seen (issue_number, gh_created_at, content_sha256, labels_at_seen)"
                " values (%s, %s, %s, %s) on conflict do nothing returning issue_number",
                [it["number"], utc(it["created_at"]), h, [l["name"] for l in it["labels"]]]).fetchone()
            if first_sight:
                area, needs_details = rules_v0.guess(it["title"], it["body"])
                db.execute(
                    "insert into prereg.predictions (issue_number, champion_id, area, needs_details, input_sha256)"
                    " values (%s, %s, %s, %s, %s)",
                    [it["number"], rules_v0.CHAMPION_ID, area, needs_details, h])
                saved += 1
        db.commit()  # first sight and the baseline are saved before any model call
        failure = None
        try:
            n = champion_pass(db, token, {it["number"]: it for it in issues})
        except BaseException as e:  # record the run and its outputs first, then fail loudly
            db.rollback()
            n, failure = {"error": type(e).__name__}, e
        pending = db.execute(
            "select count(*) from prereg.predictions"
            " where id > coalesce((select max(upto_prediction_id) from prereg.anchors), 0)").fetchone()[0]
        event.update(issues=len(issues), saved=saved, pending=pending, champion=n)
        db.execute("insert into prereg.run_events (kind, data) values ('polled', %s)", [Jsonb(event)])
    anchor = "yes" if pending or os.environ.get("ANCHOR_FILE", "").strip() else "no"
    print(f"polled http={event.get('http_status')} issues={len(issues)} saved={saved} pending={pending}"
          f" champion: {' '.join(f'{k}={v}' for k, v in n.items())}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"pending={pending}\nanchor={anchor}\n")
    if failure:
        raise failure
    if n["errors"] and not (n["guessed"] or n["refused"] or n["invalid"]):  # no call got any answer
        sys.exit("every champion call failed: check the Anthropic key and status page")  # fail loudly


if __name__ == "__main__":
    main()
