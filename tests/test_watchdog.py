"""The watchdog's checks (ops/watchdog.py) on the test database (see tests/setup_test_db.py), with a fake GitHub.
The slot rule itself is replayed against a real outage in tests/test_quiet_failure.py.

  PREREG_TEST_ADMIN_URL=... python tests/test_watchdog.py
"""
import json
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url, role_url  # noqa: E402
from ops import watchdog  # noqa: E402

NOW = datetime.now(timezone.utc)
TICK = {"cadence_min": 15, "at_minute": 7, "grace_min": 45}
WATCH = next(j for j in tomllib.loads((ROOT / "agents/registry.toml").read_text())["job"] if j["id"] == "watch/watch")


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def fake_gh(fail_upstream=False, runs=()):  # runs: (workflow file, event, start) of runs that succeeded
    def gh(url, token):
        if url.endswith("/actions/workflows"):
            return {"workflows": [{"path": ".github/workflows/tick.yml", "state": "active"},
                                  {"path": ".github/workflows/old.yml", "state": "disabled_manually"}]}
        if "/actions/workflows/" in url:  # each event query gets only its own runs
            return {"workflow_runs": [{"run_started_at": iso(start), "conclusion": "success"}
                                      for name, event, start in runs if f"/{name}/runs?event={event}&" in url]}
        if fail_upstream:
            raise TimeoutError("upstream")
        return [{"number": 777001, "created_at": iso(NOW - timedelta(minutes=75))},  # never seen: missing
                {"number": 9901, "created_at": iso(NOW - timedelta(minutes=80))},  # in the ledger
                {"number": 777002, "created_at": iso(NOW - timedelta(minutes=75)), "pull_request": {}}]  # a PR
    return gh


def polled(t, slot, saw_upstream=True, trigger="schedule"):  # the backup clock starts its ticks 12 minutes in
    start = (slot + timedelta(minutes=9 if trigger == "schedule" else 12)).isoformat()
    t.execute("select prereg.log_event('polled', %s)", [Jsonb({
        "trigger": trigger, "planned_start": slot.isoformat() if trigger == "schedule" else start, "actual_start": start,
        "http_status": 200, "lost": 0, "token_expires": f"{NOW + timedelta(days=3):%Y-%m-%d %H:%M:%S} UTC",
        "champion": {"guessed": 1, "errors": 0}, **({"newest_upstream": 777003} if saw_upstream else {})})])


def main():
    os.environ["GITHUB_REPOSITORY"] = "Dulatormanov/preregistered"
    with psycopg.connect(admin_url(), autocommit=True) as a:  # an empty ledger, as in tests/test_tick.py
        a.execute("select pgmq.purge_queue('triage_events'), pgmq.purge_queue('triage_dlq')")
        a.execute("set role prereg_owner")
        a.execute("truncate prereg.outcomes, prereg.runs, prereg.steps, prereg.run_events, prereg.anchors,"
                  " prereg.predictions, prereg.issues_seen restart identity")
        a.execute("reset role")
        a.execute("select pgmq.send('triage_events', '{\"issue_number\": 9902}')")  # malformed: a dead letter
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:
        assert t.execute("select * from prereg.claim_next(30, 'test')").fetchone() is None
        t.execute("select prereg.enqueue_issue(9901, now(), 'h', '{}', 'haiku55-p0', %s)",
                  [Jsonb({"area": "other", "needs_details": False, "input_sha256": "h"})])
        polled(t, NOW - timedelta(hours=3))  # only an old tick, so the last 2 closed slots have none
    with psycopg.connect(admin_url(), autocommit=True) as a:  # test-only time travel: an old message and guess
        a.execute("update pgmq.q_triage_events set enqueued_at = now() - interval '2 hours'")
        a.execute("set role prereg_owner; update prereg.predictions set created_at = now() - interval '1 hour'")

    watchdog.gh = fake_gh()
    with psycopg.connect(role_url("observer"), autocommit=True) as o:
        alerts = watchdog.check(o, "token", NOW)
    want = {"missed:tick/poll", "dead_letters", "queue_stuck", "unanchored", "token_expiry", "workflow_off",
            "upstream_missing"}
    assert want <= alerts.keys() and "missed:watch/watch" in alerts, sorted(alerts)  # no watch.yml run at all
    assert "777001" not in str(alerts) and "9901" not in str(alerts)  # alert texts hold counts, never numbers
    assert not alerts["missed:tick/poll"].endswith(watchdog.NEW), alerts  # missed for hours: on at the last run too

    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:  # every slot the rule looks at gets a tick:
        last = watchdog.slot_of(TICK, NOW - timedelta(minutes=45))  # from the schedule, or for 2 in a row the backup clock
        for i in range(watchdog.lookback(TICK) + 1):
            polled(t, last - timedelta(minutes=15 * i), trigger="workflow_dispatch" if i in (1, 2) else "schedule")
    newest = watchdog.slot_of(WATCH, NOW - timedelta(minutes=WATCH["grace_min"]))  # watch.yml's newest closed slot
    served = [(newest - timedelta(minutes=WATCH["cadence_min"] * i), event)  # the 2 newest: one by the schedule,
              for i, event in ((0, "workflow_dispatch"), (1, "schedule"))]  # one by the backup clock 8 minutes in
    watchdog.gh = fake_gh(fail_upstream=True, runs=[("watch.yml", event, s + timedelta(minutes=8)) for s, event in served])
    with psycopg.connect(role_url("observer"), autocommit=True) as o:
        alerts = watchdog.check(o, "token", NOW)
    assert "missed:tick/poll" not in alerts and "missed:watch/watch" not in alerts, alerts
    assert "upstream_read" in alerts and "upstream_missing" not in alerts, alerts
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:  # the 2 slots before those get a tick too
        for i in (6, 7):
            polled(t, last - timedelta(minutes=15 * i))
    with psycopg.connect(admin_url(), autocommit=True) as a:  # test-only: the 2 newest closed slots lose theirs
        a.execute("set role prereg_owner")
        a.execute("delete from prereg.run_events where kind = 'polled' and (data->>'actual_start')::timestamptz >= %s",
                  [last - timedelta(minutes=15)])
    with psycopg.connect(role_url("observer"), autocommit=True) as o:  # off at the last run, so new
        assert watchdog.check(o, "token", NOW)["missed:tick/poll"].endswith(watchdog.NEW)
    suite = next(j for j in tomllib.loads((ROOT / "agents/registry.toml").read_text())["job"] if j["id"] == "suite/run")
    watchdog.gh = fake_gh(runs=[("suite.yml", "workflow_dispatch", NOW - timedelta(hours=1))])
    assert watchdog.evidence(None, suite, NOW - timedelta(days=8), "token") == []  # by hand: not the A/A pair
    t1, t2 = NOW.replace(microsecond=0) - timedelta(hours=2), NOW.replace(microsecond=0) - timedelta(hours=1)
    watchdog.gh = fake_gh(runs=[("watch.yml", "schedule", t1), ("watch.yml", "workflow_dispatch", t2)])
    assert [started for _, started, _, _ in watchdog.evidence(None, WATCH, NOW - timedelta(days=1), "token")] == [
        t1, t2]  # for the watcher, both kinds of run count
    silent = [(last - timedelta(minutes=15 * i), last - timedelta(minutes=15 * i - 9), True, 0) for i in range(8)]
    assert watchdog.slot_alert(TICK, silent, NOW)  # ticks that "succeeded" but saw no upstream issue did nothing
    def ticks(missing):  # a healthy tick in each of the last 8 slots, except the missing ones
        slots = [last - timedelta(minutes=15 * i) for i in range(8) if i not in missing]
        return [(slot, slot + timedelta(minutes=9), True, 1) for slot in slots]
    assert not watchdog.slot_alert(TICK, ticks({2}), NOW)  # one missed slot is not an alert
    assert watchdog.slot_alert(TICK, ticks({2, 3}), NOW)  # two in a row are, even behind the newest slot
    before = NOW - timedelta(minutes=watchdog.EVERY_MIN)  # the watchdog's last run, as check() replays it
    assert watchdog.slot_alert(TICK, ticks({0, 1}), NOW) and not watchdog.slot_alert(TICK, ticks({0, 1}), before)  # new
    assert watchdog.slot_alert(TICK, ticks({4, 5}), before)  # an older pair was on at the last run too: a repeat
    young = dict(TICK, first_slot=(NOW - timedelta(minutes=50)).isoformat())  # a job too new for 2 closed slots
    assert watchdog.slot_alert(young, [], NOW) is False and watchdog.slot_alert(TICK, [], NOW) is True
    from ops.backup_clock import WORKFLOWS, slot  # the backup clock's slots are the watchdog's: 10:04 belongs to 09:52
    assert [slot(datetime(2026, 11, 5, 10, m, 30, tzinfo=timezone.utc)).strftime("%H:%M") for m in (4, 7, 19, 21)] == [
        "09:52", "10:07", "10:07", "10:07"]
    at = {name: [slot(datetime(2026, 11, 5, 10, m, 30, tzinfo=timezone.utc), first, every).strftime("%H:%M")
                 for m in (4, 19, 34, 49)] for name, first, every in WORKFLOWS}  # the slot at each minute cron runs it
    assert at == {"tick.yml": ["09:52", "10:07", "10:22", "10:37"],  # 12 minutes into each tick slot
                  "watchdog.yml": ["09:41", "10:11", "10:11", "10:41"],  # 8 and 23 minutes into a watchdog slot
                  "watch.yml": ["09:41", "09:41", "09:41", "10:41"]}, at  # from 8 minutes into a watcher slot
    jobs = {"tick.yml": TICK, "watchdog.yml": {"cadence_min": watchdog.EVERY_MIN, "at_minute": 11}, "watch.yml": WATCH}
    assert all(slot(t, first, every) == watchdog.slot_of(jobs[name], t) for name, first, every in WORKFLOWS
               for t in (NOW, NOW + timedelta(minutes=7)))
    from ops import open_alerts  # with this alert type's 6-hour budget spent, only a new incident goes out
    calls, real_run = [], subprocess.run
    subprocess.run = lambda args, **kw: calls.append(args[:3]) or subprocess.CompletedProcess(args, 0, stdout="[]")
    open_alerts.spend = lambda kind, topic="": False
    try:
        for line, sent in ((f"tick/poll: 2 slots in a row had no healthy run{watchdog.NEW}", True),
                           ("tick/poll: 2 slots in a row had no healthy run", False)):
            calls.clear()
            os.environ["ALERTS"] = json.dumps({"missed:tick/poll": line})
            open_alerts.main()
            assert (["gh", "issue", "create"] in calls) is sent, (line, calls)
    finally:
        subprocess.run = real_run
    print(f"ok: the watchdog raises each of its {len(want) + 1} alert types, and none for a healthy tick or watcher"
          " slot, whether the schedule or the backup clock started the run; a new incident goes out over the"
          " contact budget, a repeat does not")


if __name__ == "__main__":
    main()
