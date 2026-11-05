"""The weekly report v0 on the test database (see tests/setup_test_db.py): seeded through the job functions only,
read as observer, with a fake GitHub run list.

  PREREG_TEST_ADMIN_URL=... python tests/test_weekly_report.py
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url, role_url  # noqa: E402
from ops import weekly_report  # noqa: E402

STEP = {"champion_id": "haiku55-p0", "model": "claude-haiku-5-5", "status": "ok", "request_id": "req_test",
        "input_tokens": 1000, "output_tokens": 16, "cache_read_tokens": 0, "cache_write_tokens": 0,
        "cost_usd": 0.000108, "lock_sha256": "x" * 64, "error": None}


def main():
    with psycopg.connect(admin_url(), autocommit=True) as a:  # an empty ledger, as in tests/test_tick.py
        a.execute("select pgmq.purge_queue('triage_events'), pgmq.purge_queue('triage_dlq')")
        a.execute("set role prereg_owner")
        a.execute("truncate prereg.outcomes, prereg.runs, prereg.steps, prereg.run_events, prereg.anchors,"
                  " prereg.predictions, prereg.issues_seen restart identity")
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:
        t.execute("select prereg.enqueue_issue(9901, now(), 'h', '{}', 'haiku55-p0', %s)",
                  [Jsonb({"area": "other", "needs_details": False, "input_sha256": "h"})])
        attempt = t.execute("select * from prereg.claim_next(30, 'test')").fetchone()[0]
        t.execute("select prereg.complete(%s, 'guessed', 'auth', false, 'h', %s)", [attempt, Jsonb(STEP)])
        for minute, trigger in ((7, "schedule"), (7, "schedule"), (22, "schedule"), (30, "workflow_dispatch")):
            t.execute("select prereg.log_event('polled', %s)",  # one slot polled twice counts once
                      [Jsonb({"trigger": trigger, "planned_start": (today + timedelta(minutes=minute)).isoformat()})])
    with psycopg.connect(admin_url(), autocommit=True) as a:  # a malformed message becomes a dead letter
        a.execute("select pgmq.send('triage_events', '{\"issue_number\": 9902}')")
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:
        assert t.execute("select * from prereg.claim_next(30, 'test')").fetchone() is None
    with psycopg.connect(role_url("notary"), autocommit=True) as n:
        n.execute("select prereg.record_anchor('canon=v1 kind=rows upto=2 n=2 rows=x', 'chain-x', 2, 1, now())")

    start = today - timedelta(days=6)
    with psycopg.connect(role_url("observer"), autocommit=True) as o:
        o.execute("set timezone = 'UTC'")
        rows = o.execute(weekly_report.LEDGER, {"start": start}).fetchall()
    assert len(rows) == 7 and all(r[1:] == (0, 0, 0, 0, 0, 0, 0) for r in rows[:6])
    assert rows[6] == (today.date(), 2, 1, 1, 1, 0, 1, Decimal("0.000108")), rows[6]

    asked = []

    def get(path):  # today, two pages: 100 tick runs, then a failed tick and a CI run; no run on the other days
        asked.append(path)
        if f"created={today:%Y-%m-%d}&" not in path:
            return {"workflow_runs": []}
        run = {"path": ".github/workflows/tick.yml", "created_at": f"{today:%Y-%m-%d}T00:10:00Z", "status": "completed",
               "conclusion": "success", "run_started_at": f"{today:%Y-%m-%d}T00:10:00Z",
               "updated_at": f"{today:%Y-%m-%d}T00:11:00Z"}
        if path.endswith("&page=1"):
            return {"workflow_runs": [run] * 100}
        return {"workflow_runs": [dict(run, conclusion="failure"), dict(run, path=".github/workflows/ci.yml")]}
    runs = weekly_report.runs_by_day(start, get)
    assert runs[today.date().isoformat()] == {"ticks": 101, "failed": 1, "minutes": 102.0}
    assert len(asked) == 8 and sum("&page=2" in p for p in asked) == 1  # one query per day, 7 days and today

    text = weekly_report.render(start, rows, runs, [("baseline", 4, 1, 5), ("champion", 4, 3, 5)])  # lint-checked
    assert "champion 3 of 4 counting guesses right (5 scorable)" in text
    assert f"| {today:%a %b} {today.day} | 101 | 94 | 1 | 1 | 1 | 1 | 0 | 1 | 0.0001 | 102 |" in text, text
    assert "9901" not in text and "9902" not in text  # no issue numbers in public text
    week = weekly_report.numbers(start, rows, runs, [("champion", 4, 3, 5)])
    assert (week["tick_runs"], week["missed_slots"], week["champion_guesses"], week["dead_letters"]) == (101, 96 * 7 - 2, 1, 1)
    assert week["live_window"]["champion"] == {"counting_guesses": 4, "right": 3, "scorable": 5}

    # The live window so far is the window's issues only (Nov 14 to Dec 4), scored as `make tables` does. 9903 is
    # in it; 9904 (Nov 10) shares its Monday week but not the window; 9905 is after it. The numbers are plain ints.
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:
        for n, created in ((9903, "2026-11-20 12:00+00"), (9904, "2026-11-10 12:00+00"), (9905, "2026-12-06 12:00+00")):
            t.execute("select prereg.enqueue_issue(%s, %s, 'h', '{}', 'haiku55-p2', %s)",
                      [n, created, Jsonb({"area": "other", "needs_details": False, "input_sha256": "h"})])
            attempt = t.execute("select * from prereg.claim_next(30, 'test')").fetchone()[0]
            t.execute("select prereg.complete(%s, 'guessed', 'auth', false, 'h', %s)",
                      [attempt, Jsonb(dict(STEP, champion_id="haiku55-p2"))])
    with psycopg.connect(role_url("notary"), autocommit=True) as n:
        n.execute("select prereg.record_anchor('canon=v1 kind=rows upto=8 n=6 rows=y', 'chain-y', 8, 2,"
                  " timestamptz '2026-11-06 00:00+00')")  # its time only has to come before each label
    with psycopg.connect(role_url("collector"), autocommit=True) as k:
        for n, at in ((9903, "2026-11-21 12:00+00"), (9904, "2026-11-11 12:00+00"), (9905, "2026-12-07 12:00+00")):
            k.execute("select prereg.record_outcome(%s, %s, 'auth', 'add', 'User', false, %s)", [n, f"w{n}", at])
    from tools import readme_numbers
    from tools.tables import window_so_far
    with psycopg.connect(role_url("observer"), autocommit=True) as o:
        so_far = window_so_far(o)
        readme = readme_numbers.block(o)
    assert so_far == [("champion", 1, 1, 1), ("baseline", 1, 0, 1)], so_far
    assert json.loads(json.dumps(weekly_report.numbers(start, rows, runs, so_far)))["live_window"]["champion"] == {
        "counting_guesses": 1, "right": 1, "scorable": 1}
    assert "champion 1 of 1 counting guesses right (1 scorable); baseline 0 of 1" in readme, readme

    # The post step keeps the agent's summary only if it breaks none of the four failure modes.
    import subprocess, tempfile  # noqa: E401
    tmp = Path(tempfile.mkdtemp())
    (tmp / "data.json").write_text(json.dumps(week))
    for summary, kept in (("This week there were 101 tick runs.", True), ("Thanks to the team for 101 tick runs.", False)):
        (tmp / "report.md").write_text(text)
        (tmp / "summary.txt").write_text(summary)
        subprocess.run([sys.executable, "-m", "agents.report_post", tmp / "report.md", tmp / "summary.txt",
                        tmp / "data.json"], cwd=ROOT, check=True, capture_output=True)
        posted = (tmp / "report.md").read_text()
        assert (summary in posted) is kept and ("was left out" in posted) is not kept, posted[:300]
    print("ok: the weekly report counts slots, guesses, dead letters, anchors, spend and runs per day")


if __name__ == "__main__":
    main()
