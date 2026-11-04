"""The weekly report v0, with no model: per UTC day, for the 7 full days before today, the ticks, missed slots,
failed runs, guesses, dead letters, anchors, spend and Actions time.

  OBSERVER_DB_URL=... GH_TOKEN=... GITHUB_REPOSITORY=owner/repo python -m ops.weekly_report > report.md
It reads the ledger as observer and the run list with GITHUB_TOKEN. Counts only, never an issue number or
issue text: weekly.yml posts the output as one comment on the Weekly reports issue.
"""
import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import psycopg

from scripts.lint_refs import check as lint_refs

SLOTS_PER_DAY = 96  # tick.yml has 4 cron lines an hour
LEDGER = """
select d::date,
  (select count(distinct e.data->>'planned_start') from prereg.run_events e
    where e.kind = 'polled' and e.data->>'trigger' = 'schedule'
      and (e.data->>'planned_start')::timestamptz >= d and (e.data->>'planned_start')::timestamptz < d + interval '1 day'),
  (select count(*) filter (where p.champion_id <> 'rules_v0') from prereg.predictions p
    where p.created_at >= d and p.created_at < d + interval '1 day'),
  (select count(*) filter (where p.champion_id = 'rules_v0') from prereg.predictions p
    where p.created_at >= d and p.created_at < d + interval '1 day'),
  (select count(*) from prereg.run_events e where e.kind = 'dead_letter' and e.created_at >= d and e.created_at < d + interval '1 day'),
  (select count(*) from prereg.run_events e where e.kind = 'expired' and e.created_at >= d and e.created_at < d + interval '1 day'),
  (select count(*) from prereg.anchors a where a.comment_created_at >= d and a.comment_created_at < d + interval '1 day'),
  (select coalesce(sum(s.cost_usd), 0) from prereg.steps s where s.created_at >= d and s.created_at < d + interval '1 day')
from generate_series(%(start)s::timestamptz, %(start)s::timestamptz + interval '6 days', interval '1 day') d
order by d"""
HEAD = ("| Day (UTC) | Tick runs | Missed slots | Failed runs | Champion guesses | Baseline guesses | Dead letters"
        " | Expired | Anchors | Spend (USD) | Actions (min) |\n|---|---|---|---|---|---|---|---|---|---|---|")


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def runs_by_day(start, get):
    """This repo's workflow runs created on or after start, by UTC day."""
    out, page = defaultdict(lambda: {"ticks": 0, "failed": 0, "minutes": 0.0}), 1
    while True:  # note: GitHub lists at most 1,000 runs for a created filter, about 10 days of ticks
        batch = get(f"/actions/runs?created=%3E%3D{start:%Y-%m-%d}&per_page=100&page={page}")["workflow_runs"]
        for r in batch:
            day = out[r["created_at"][:10]]
            day["ticks"] += r["path"].endswith("/tick.yml")
            day["failed"] += r["conclusion"] in ("failure", "timed_out", "startup_failure")
            if r["status"] == "completed" and r.get("run_started_at"):  # wall clock, approval waits included
                day["minutes"] += (utc(r["updated_at"]) - utc(r["run_started_at"])).total_seconds() / 60
        if len(batch) < 100:
            return out
        page += 1


def render(start, rows, runs):
    end = start + timedelta(days=6)
    lines = [f"**Weekly report v0, {start:%b} {start.day} to {end:%b} {end.day}, UTC.** Counts only; no model wrote"
             f" this. A missed slot is a 15-minute slot with no scheduled tick.", "", HEAD]
    for day, slots, champion, baseline, dead, expired, anchors, spend in rows:
        r = runs.get(day.isoformat(), {"ticks": 0, "failed": 0, "minutes": 0.0})
        lines.append(f"| {day:%a %b} {day.day} | {r['ticks']} | {SLOTS_PER_DAY - slots} | {r['failed']} | {champion}"
                     f" | {baseline} | {dead} | {expired} | {anchors} | {spend:.4f} | {r['minutes']:.0f} |")
    text = "\n".join(lines)
    if lint_refs(text):  # every posted text passes the reference lint first
        raise SystemExit("the report failed the reference lint")
    return text


def get(path):
    req = urllib.request.Request(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}", headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "preregistered"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
    with psycopg.connect(os.environ["OBSERVER_DB_URL"], autocommit=True) as db:
        db.execute("set timezone = 'UTC'")  # the days are UTC days
        rows = db.execute(LEDGER, {"start": start}).fetchall()
        first = db.execute("select min(created_at)::date from prereg.run_events where kind = 'polled'").fetchone()[0]
    rows = [r for r in rows if first is None or r[0] >= first]  # days before the first tick are left out
    print(render(start, rows, runs_by_day(start, get)))


if __name__ == "__main__":
    main()
