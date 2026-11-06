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
from pathlib import Path

import psycopg

from scripts.lint_refs import check as lint_refs
from tools.tables import window_so_far

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
    """This repo's workflow runs created from start's UTC day to today, by UTC day. One query per day: GitHub lists
    at most 1,000 runs for one created filter, and the tick, the watchdog and the watcher make more in a week."""
    out = defaultdict(lambda: {"ticks": 0, "failed": 0, "minutes": 0.0})
    day = start.date()
    while day <= datetime.now(timezone.utc).date():
        page = 1
        while True:
            batch = get(f"/actions/runs?created={day:%Y-%m-%d}&per_page=100&page={page}")["workflow_runs"]
            for r in batch:
                d = out[r["created_at"][:10]]
                d["ticks"] += r["path"].endswith("/tick.yml")
                d["failed"] += r["conclusion"] in ("failure", "timed_out", "startup_failure")
                if r["status"] == "completed" and r.get("run_started_at"):  # wall clock, approval waits included
                    d["minutes"] += (utc(r["updated_at"]) - utc(r["run_started_at"])).total_seconds() / 60
            if len(batch) < 100:
                break
            page += 1
        day += timedelta(days=1)
    return out


def agreement_line(so_far):
    """One line: the live window so far, under the pre-registered rule, as `make tables` scores it."""
    parts = [f"{series} {matched} of {counting} counting guesses right ({scorable} scorable)"
             for series, counting, matched, scorable in so_far]
    return "Live window so far (labels still arrive for 7 days): " + "; ".join(parts) + "."


def render(start, rows, runs, so_far=()):
    end = start + timedelta(days=6)
    lines = [f"**Weekly report v0, {start:%b} {start.day} to {end:%b} {end.day}, UTC.** Counts only; no model wrote"
             f" this. A missed slot is a 15-minute slot with no scheduled tick.", "", HEAD]
    tail = ["", agreement_line(so_far) if so_far else "", "Independent project, not affiliated with Supabase."]
    for day, slots, champion, baseline, dead, expired, anchors, spend in rows:
        r = runs.get(day.isoformat(), {"ticks": 0, "failed": 0, "minutes": 0.0})
        lines.append(f"| {day:%a %b} {day.day} | {r['ticks']} | {SLOTS_PER_DAY - slots} | {r['failed']} | {champion}"
                     f" | {baseline} | {dead} | {expired} | {anchors} | {spend:.4f} | {r['minutes']:.0f} |")
    text = "\n".join(lines + tail)
    if lint_refs(text):  # every posted text passes the reference lint first
        raise SystemExit("the report failed the reference lint")
    return text


def numbers(start, rows, runs, so_far):
    """The week in numbers: totals over its days, and the live window so far. Counts only."""
    days = [r[0].isoformat() for r in rows]
    total = lambda i: sum(r[i] for r in rows)  # noqa: E731
    return {"week": f"{start:%Y-%m-%d} to {start + timedelta(days=6):%Y-%m-%d}", "days_reported": len(rows),
            "tick_runs": sum(runs.get(d, {}).get("ticks", 0) for d in days),
            "missed_slots": SLOTS_PER_DAY * len(rows) - total(1),
            "failed_runs": sum(runs.get(d, {}).get("failed", 0) for d in days),
            "champion_guesses": total(2), "baseline_guesses": total(3), "dead_letters": total(4), "expired": total(5),
            "anchors": total(6), "spend_usd": round(float(sum(r[7] for r in rows)), 4),
            "live_window": {series: {"counting_guesses": counting, "right": matched, "scorable": scorable}
                            for series, counting, matched, scorable in so_far}}


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
        so_far = window_so_far(db)
    rows = [r for r in rows if first is None or r[0] >= first]  # days before the first tick are left out
    runs = runs_by_day(start, get)
    print(render(start, rows, runs, so_far))
    if os.environ.get("REPORT_DATA"):  # the week's numbers, for the report agent (agents/weekly_report.py)
        Path(os.environ["REPORT_DATA"]).write_text(json.dumps(numbers(start, rows, runs, so_far), sort_keys=True))


if __name__ == "__main__":
    main()
