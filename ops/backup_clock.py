"""The backup clock (ADR-001): cron on the owner's server runs this 12 minutes after each tick slot.

  4,19,34,49 * * * * /usr/bin/python3 ~/prereg/backup_clock.py >> ~/prereg/backup_clock.log 2>&1
It covers the tick, the watchdog, the model watcher, the four daily jobs and the three Monday jobs
(agents/registry.toml has their slots). If no scheduled or started run of a workflow was created since its current
slot began, it starts one (workflow_dispatch), with the inputs that make it do what the schedule does, so the run is
still a public GitHub Actions run. Push runs do not count: a push run of the suite is not the Monday A/A pair. The token in ./token,
next to the script, is fine-grained: Actions read and write, on this repo only (CREDENTIALS.md). A duplicate run is
harmless: the ledger keeps one first sight per issue and per model, an alert repeat gets at most one issue or
comment per 6 hours, and each daily job queues behind its own concurrency group and skips work already done. A
copy of this file must compile before cron runs it (python3 -m py_compile): a script that does not compile starts
nothing. Standard library only, because the server has no packages for it.
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com/repos/Dulatormanov/preregistered/actions/workflows"
EPOCH = datetime(2026, 11, 2, tzinfo=timezone.utc)  # a Monday, as in ops/watchdog.py
WORKFLOWS = [("tick.yml", 7, 15), ("watchdog.yml", 11, 30), ("watch.yml", 41, 60),  # file, first minute, period
             ("reveal.yml", 257, 1440), ("drift.yml", 331, 1440), ("outcomes.yml", 373, 1440),  # daily: 04:17, 05:31,
             ("sealed.yml", 467, 1440),  # 06:13 and 07:47 UTC
             ("suite.yml", 373, 10080), ("known-bad-control.yml", 413, 10080), ("weekly.yml", 443, 10080)]  # Monday
INPUTS = {"suite.yml": {"scheduled": "true"}, "weekly.yml": {"post": "true"}}  # what the schedule does


def slot(now, first=7, every=15):
    """The slot a time falls in: slots start `first` minutes after the epoch, then every `every` minutes, as the
    watchdog's slot_of counts them. The defaults are tick.yml's slots: minutes 7, 22, 37 and 52 of each hour."""
    minutes = (now - EPOCH) // timedelta(minutes=1) - first
    return EPOCH + timedelta(minutes=first + minutes // every * every)


def main():
    token = (Path(__file__).resolve().parent / "token").read_text().strip()

    def call(method, url, body=None):
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "prereg-backup-clock"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r) if r.status == 200 else None

    now = datetime.now(timezone.utc)
    for name, first, every in WORKFLOWS:
        start = slot(now, first, every)
        try:  # a failed call must not stop the next workflow's check
            runs = [r for event in ("schedule", "workflow_dispatch")
                    for r in call("GET", f"{API}/{name}/runs?event={event}&per_page=5")["workflow_runs"]]
            if any(datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= start for r in runs):
                result = f"slot {start:%H:%M} already has a run"
            else:
                call("POST", f"{API}/{name}/dispatches", {"ref": "main", **({"inputs": INPUTS[name]} if name in INPUTS else {})})
                result = f"no run since slot {start:%H:%M}, so one was started"
        except Exception as e:
            result = f"slot {start:%H:%M}: failed ({e})"
        print(f"{now:%Y-%m-%d %H:%M} UTC: {name}: {result}")


if __name__ == "__main__":
    main()
