"""The August replay: the real outage that began on 2026-08-03 (tests/fixtures/outage_2026_08_03.csv), run
through the watchdog's rules in four variants. In August nothing alerted, and the owner found the outage by hand
three weeks later. Here every variant must raise an alert within 4 hours, and the healthy weeks before it none.

  python tests/test_quiet_failure.py
"""
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops.watchdog import queue_alerts, slot_alert  # noqa: E402

JOBS = {"drafter": {"cadence_min": 180, "at_minute": 0, "grace_min": 60},  # cron: every 3 hours at :00
        "submitter": {"cadence_min": 180, "at_minute": 90, "grace_min": 60}}  # and at :30, 90 minutes later
WATCHDOG = timedelta(minutes=30)  # how often the watchdog runs
BOUND = timedelta(hours=4)


def load():
    with open(ROOT / "tests/fixtures/outage_2026_08_03.csv") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    return [(r["job"], datetime.strptime(r["started"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc),
             int(r["exit_code"])) for r in rows]


def first_alert(entry, runs, start, end, queue_from=None):
    """The first watchdog run in [start, end) that raises an alert, or None."""
    t = start
    while t < end:
        seen = [(None, began, ok, outputs) for began, ok, outputs in runs if began <= t]
        oldest = (t - queue_from).total_seconds() if queue_from and t > queue_from else 0
        if slot_alert(entry, seen, t) or queue_alerts(0, oldest):
            return t
        t += WATCHDOG
    return None


def main():
    runs = load()
    healthy_from, end = datetime(2026, 7, 22, tzinfo=timezone.utc), datetime(2026, 9, 5, tzinfo=timezone.utc)
    for job, entry in JOBS.items():
        mine = [(t, code) for j, t, code in runs if j == job]
        failed = min(t for t, code in mine if code)  # the first run that hit the expired token
        fixed = max(t for t, code in mine if code)
        before = [(t, True, 1) for t, code in mine if t < failed]
        assert first_alert(entry, before, healthy_from, failed) is None, f"{job}: a false alarm before the outage"
        variants = {
            "failed runs": [(t, code == 0, 1) for t, code in mine],
            "no runs": before,
            "a silent success": [(t, True, 0 if code else 1) for t, code in mine],
        }
        for name, replay in variants.items():
            at = first_alert(entry, replay, failed, end)
            assert at and at - failed <= BOUND, f"{job}, {name}: alert at {at}"
            print(f"ok: {job}, {name}: alert {(at - failed) / timedelta(hours=1):.1f} h after the first failed run"
                  f" (August: found by hand {(fixed - failed).days} days later)")
        drain = [(t, True, 1) for t, code in mine]  # every run says it worked, but the queue never shrinks
        at = first_alert(entry, drain, failed, end, queue_from=failed)
        assert at and at - failed <= BOUND, f"{job}, a drain that does nothing: alert at {at}"
        print(f"ok: {job}, a drain that does nothing: alert {(at - failed) / timedelta(hours=1):.1f} h after it began")


if __name__ == "__main__":
    main()
