"""The watchdog (Build day 1): it notices a run that never happened, and a run that "succeeded" but did nothing.

Every 30 minutes (watchdog.yml) it checks:
- slots: each job in agents/registry.toml with a cadence must have a healthy run in each slot: a run that
  succeeded and produced its output. A tick's output is the upstream list it read: a tick that saw no upstream
  issue at all did nothing. Two unhealthy slots in a row raise an alert for that job, wherever they fall
  between two watchdog runs;
- the queue: any dead letter, or a message older than 60 minutes (a drain that does nothing);
- the anchors: a guess saved more than 30 minutes ago that no anchor covers yet;
- the read token: it expires within 14 days;
- the workflows: any that is not "active";
- upstream: an issue created 60 to 90 minutes ago that the ledger never saw. It reads upstream itself, with
  GITHUB_TOKEN, so a broken read token cannot blind it. A failed upstream read is an alert of its own.
It prints one line per alert, counts only, and gives the alert types to the alert job, which opens one issue
per type. At the end it pings its own Healthchecks check, so a watchdog that stops running is noticed too.
"""
import json
import math
import os
import tomllib
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPOCH = datetime(2026, 11, 2, tzinfo=timezone.utc)  # a Monday: every cadence counts its slots from here
UPSTREAM = "https://api.github.com/repos/supabase/supabase/issues"
OLDEST_MESSAGE_S, UNANCHORED, TOKEN_DAYS = 3600, timedelta(minutes=30), 14
UPSTREAM_FROM, UPSTREAM_TO = timedelta(minutes=90), timedelta(minutes=60)  # the window it checks, before now
EVERY_MIN = 30  # how often watchdog.yml runs


def slot_of(entry, t):
    """The slot a run that started at t belongs to: the latest one at or before t."""
    minutes = (t - EPOCH) // timedelta(minutes=1) - entry["at_minute"]
    return EPOCH + timedelta(minutes=entry["at_minute"] + minutes // entry["cadence_min"] * entry["cadence_min"])


def lookback(entry):
    """How many closed slots to look at: enough to cover the slots closed since the watchdog's run before last."""
    return 1 + math.ceil(2 * EVERY_MIN / entry["cadence_min"])


def slot_alert(entry, runs, now):
    """True if two neighbouring closed slots among the job's last few are both unhealthy.

    runs: (slot, started, ok, outputs) tuples; slot is None if the run's slot must be worked out from started.
    A slot is closed once its grace has passed. It is healthy if a run for it started within the grace,
    succeeded, and produced at least min_outputs (1 by default). Slots before the entry's first_slot do not count.
    """
    grace, cadence = timedelta(minutes=entry["grace_min"]), timedelta(minutes=entry["cadence_min"])
    first = datetime.fromisoformat(entry["first_slot"]) if "first_slot" in entry else None
    healthy = {slot or slot_of(entry, started) for slot, started, ok, outputs in runs
               if ok and outputs >= entry.get("min_outputs", 1) and started < (slot or slot_of(entry, started)) + grace}
    last = slot_of(entry, now - grace)
    closed = [last - i * cadence for i in range(lookback(entry) + 1)]
    return any(newer not in healthy and older not in healthy for newer, older in zip(closed, closed[1:])
               if first is None or older >= first)  # a slot before first_slot: the job did not exist yet


def queue_alerts(dead_letters, oldest_message_s):
    return (["dead_letters"] if dead_letters else []) + (["queue_stuck"] if oldest_message_s > OLDEST_MESSAGE_S else [])


def gh(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "preregistered",
                                               "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def poll_ok(d):
    """A tick that read GitHub, lost nothing, and got an answer whenever it called the model (as runner/poll.py)."""
    c = d.get("champion") or {}
    answered = any(c.get(k) for k in ("guessed", "refused", "invalid"))
    return (d.get("http_status") == 200 and "error" not in d and "error" not in c and not d.get("lost")
            and (answered or not c.get("errors")))


def evidence(db, entry, since, token):
    """(slot, started, ok, outputs) runs of one job since a time, from the ledger or the run list."""
    kind, _, name = entry["evidence"].partition(":")
    if kind == "event" and name == "polled":  # a scheduled tick says which slot it served; a tick that the backup
        # clock (ops/backup_clock.py) or a person started serves the slot it started in
        rows = db.execute("select data from prereg.run_events where kind = 'polled' and created_at >= %s",
                          [since]).fetchall()
        return [(utc(d["planned_start"]) if d.get("trigger") == "schedule" else None, utc(d["actual_start"]),
                 poll_ok(d), 1 if d.get("newest_upstream") else 0) for (d,) in rows]  # no upstream issue: did nothing
    if kind == "event":
        rows = db.execute("select created_at from prereg.run_events where kind = %s and created_at >= %s",
                          [name, since]).fetchall()
        return [(None, t, True, 1) for (t,) in rows]
    # A run serves the slot it started in. A run started by hand counts only for a workflow the backup clock starts:
    # a hand-started suite.yml or weekly.yml does not do the scheduled job (no A/A pair, no post). One call per
    # event, so push runs (suite.yml has them) cannot crowd the scheduled runs out of the 50.
    from ops.backup_clock import WORKFLOWS
    events = ("schedule", "workflow_dispatch") if name in {f for f, _, _ in WORKFLOWS} else ("schedule",)
    url = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/workflows/{name}/runs"
    runs = [r for event in events for r in gh(f"{url}?event={event}&per_page=50", token)["workflow_runs"]]
    return [(None, utc(r["run_started_at"]), r["conclusion"] == "success", 1) for r in runs
            if r.get("run_started_at") and utc(r["run_started_at"]) >= since]


def check(db, token, now):
    """The alerts, as {type: one line of counts}."""
    alerts = {}
    for entry in tomllib.loads((ROOT / "agents/registry.toml").read_text())["job"]:
        if "cadence_min" in entry:
            since = now - timedelta(minutes=(lookback(entry) + 3) * entry["cadence_min"] + entry["grace_min"])
            if slot_alert(entry, evidence(db, entry, since, token), now):
                alerts[f"missed:{entry['id']}"] = f"{entry['id']}: 2 slots in a row had no healthy run"
    dead, oldest = db.execute("select * from prereg.queue_health()").fetchone()
    for kind in queue_alerts(dead, oldest):
        alerts[kind] = f"queue: {dead} dead letters, oldest message {oldest // 60} minutes old"
    unanchored = db.execute("select min(created_at) from prereg.predictions where id > coalesce("
                            "(select max(upto_prediction_id) from prereg.anchors), 0)").fetchone()[0]
    if unanchored and now - unanchored > UNANCHORED:
        alerts["unanchored"] = f"a guess saved {(now - unanchored) // timedelta(minutes=1)} minutes ago has no anchor"
    expires = db.execute("select data->>'token_expires' from prereg.run_events where kind = 'polled'"
                         " and data->>'token_expires' is not null order by id desc limit 1").fetchone()
    if expires and expires[0]:
        left = datetime.strptime(expires[0][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) - now
        if left < timedelta(days=TOKEN_DAYS):
            alerts["token_expiry"] = f"the read token expires in {left.days} days"
    workflows = gh(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/workflows", token)
    off = [w["path"] for w in workflows["workflows"] if w["state"] != "active"]
    if off:
        alerts["workflow_off"] = f"{len(off)} workflows are not active: {', '.join(off)}"
    try:
        recent = [it for it in gh(f"{UPSTREAM}?state=all&sort=created&direction=desc&per_page=50", token)
                  if "pull_request" not in it and now - UPSTREAM_FROM <= utc(it["created_at"]) <= now - UPSTREAM_TO]
    except Exception as e:  # an alert of its own: it must not look like "nothing to check"
        alerts["upstream_read"] = f"the watchdog's own upstream read failed: {type(e).__name__}"
    else:
        seen = {n for (n,) in db.execute("select issue_number from prereg.issues_seen where issue_number = any(%s)",
                                         [[it["number"] for it in recent]]).fetchall()}
        missing = len(recent) - len(seen)
        if missing:
            alerts["upstream_missing"] = f"{missing} upstream issues created 60 to 90 minutes ago are not in the ledger"
    return alerts


def main():
    import psycopg  # here, so the replay test needs no database driver
    now = datetime.now(timezone.utc)
    with psycopg.connect(os.environ["OBSERVER_DB_URL"], autocommit=True) as db:  # observer: reads only
        alerts = check(db, os.environ["GH_TOKEN"], now)
    ping = os.environ.get("HC_WATCHDOG_URL", "")
    if os.environ.get("GITHUB_ACTIONS") and not ping:  # the dead-man's switch is off: say so, once, in an issue
        alerts["no_dead_mans_switch"] = "HC_WATCHDOG_URL is not set, so nobody would notice if the watchdog stopped"
    for line in alerts.values():
        print("ALERT", line)
    print(f"watchdog: {len(alerts)} alerts")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"alerts={json.dumps(alerts)}\n")
    if ping:  # the dead-man's switch: Healthchecks alerts if these pings stop. A failed ping fails the run.
        urllib.request.urlopen(ping, timeout=10)


if __name__ == "__main__":
    main()
