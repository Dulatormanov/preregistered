"""The backup clock (ADR-001): cron on the owner's server runs this 12 minutes after each tick slot.

  4,19,34,49 * * * * /usr/bin/python3 ~/prereg/backup_clock.py >> ~/prereg/backup_clock.log 2>&1
It covers the tick, the watchdog and the model watcher. If no run of a workflow was created since its current slot
began, it starts one (workflow_dispatch), so the run is still a public GitHub Actions run. The token in ./token,
next to the script, is fine-grained: Actions read and write, on this repo only (CREDENTIALS.md). A duplicate run is
harmless: the ledger keeps one first sight per issue and per model, and an alert type gets at most one issue or
comment per 6 hours. Standard library only, because the server has no packages for it.
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com/repos/Dulatormanov/preregistered/actions/workflows"
WORKFLOWS = [("tick.yml", 7, 15), ("watchdog.yml", 11, 30), ("watch.yml", 41, 60)]  # file, first minute, period


def slot(now, first=7, every=15):
    """The slot a time falls in, when slots start at minute `first` of the hour and then every `every` minutes.
    The defaults are tick.yml's slots: minutes 7, 22, 37 and 52."""
    # note: it counts minutes of the hour, so it is right only when every divides 60
    return now.replace(second=0, microsecond=0) - timedelta(minutes=(now.minute - first) % every)


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
            runs = call("GET", f"{API}/{name}/runs?per_page=5")["workflow_runs"]
            if any(datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= start for r in runs):
                result = f"slot {start:%H:%M} already has a run"
            else:  # no inputs: the defaults do what a scheduled run does
                call("POST", f"{API}/{name}/dispatches", {"ref": "main"})
                result = f"no run since slot {start:%H:%M}, so one was started"
        except Exception as e:
            result = f"slot {start:%H:%M}: failed ({e})"
        print(f"{now:%Y-%m-%d %H:%M} UTC: {name}: {result}")


if __name__ == "__main__":
    main()
