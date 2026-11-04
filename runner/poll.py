"""One tick: read new upstream issues, save one rules_v0 guess per issue, log a 'polled' event.

Prints counts only, never issue numbers or text: Actions logs are public.
"""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.types.json import Jsonb

from agents import rules_v0
from notary.canonical import content_sha256

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


def new_issues(token, cutoff, event):
    """Issues (not PRs) created at or after cutoff, newest first."""
    out = []
    for page in range(1, MAX_PAGES + 1):
        req = urllib.request.Request(
            f"{UPSTREAM}?state=all&sort=created&direction=desc&per_page={PER_PAGE}&page={page}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "preregistered"})
        with urllib.request.urlopen(req, timeout=30) as r:
            event["http_status"] = r.status
            batch = json.load(r)
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
    with psycopg.connect(os.environ["TRIAGE_DB_URL"]) as db:
        newest = db.execute("select max(gh_created_at) from prereg.issues_seen").fetchone()[0]
        cutoff = max(START, newest - OVERLAP) if newest else START
        try:
            issues = new_issues(os.environ["PREREG_READ_TOKEN"], cutoff, event)
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
        pending = db.execute(
            "select count(*) from prereg.predictions"
            " where id > coalesce((select max(upto_prediction_id) from prereg.anchors), 0)").fetchone()[0]
        event.update(issues=len(issues), saved=saved, pending=pending)
        db.execute("insert into prereg.run_events (kind, data) values ('polled', %s)", [Jsonb(event)])
    print(f"polled http={event.get('http_status')} issues={len(issues)} saved={saved} pending={pending}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"pending={pending}\n")


if __name__ == "__main__":
    main()
