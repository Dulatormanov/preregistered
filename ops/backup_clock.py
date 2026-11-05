"""The backup clock (ADR-001): cron on the owner's server runs this 12 minutes after each tick slot.

  4,19,34,49 * * * * /usr/bin/python3 ~/prereg/backup_clock.py >> ~/prereg/backup_clock.log 2>&1
If GitHub's schedule has not started tick.yml since the slot began, it starts one (workflow_dispatch), so the run is
still a public GitHub Actions run. The token in ./token, next to the script, is fine-grained: Actions read and
write, on this repo only (CREDENTIALS.md). A duplicate tick is harmless: the ledger keeps one first sight per issue.
Standard library only, because the server has no packages for it.
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com/repos/Dulatormanov/preregistered/actions/workflows/tick.yml"


def slot(now):
    """The tick slot a time falls in: tick.yml's slots start at minutes 7, 22, 37 and 52."""
    return now.replace(second=0, microsecond=0) - timedelta(minutes=(now.minute - 7) % 15)


def main():
    token = (Path(__file__).resolve().parent / "token").read_text().strip()

    def call(method, url, body=None):
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "prereg-backup-clock"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r) if r.status == 200 else None

    now = datetime.now(timezone.utc)
    start = slot(now)
    runs = call("GET", f"{API}/runs?per_page=5")["workflow_runs"]
    if any(datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= start for r in runs):
        print(f"{now:%Y-%m-%d %H:%M} UTC: slot {start:%H:%M} already has a tick")
    else:
        call("POST", f"{API}/dispatches", {"ref": "main"})
        print(f"{now:%Y-%m-%d %H:%M} UTC: no tick since slot {start:%H:%M}, so one was started")


if __name__ == "__main__":
    main()
