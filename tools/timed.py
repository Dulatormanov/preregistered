"""The timed baseline (Build day 3): how long one triage decision takes a person. The owner times 15 decisions on
dev-set issues; v_work_absorbed_monthly (Build day 5) uses the median.

  PREREG_READ_TOKEN=... python tools/timed.py
It shows one issue at a time, from the time you see it until you type an area. It appends to baseline/timed.csv:
the issue number, the seconds, and your area. Stop with q; run it again to go on.
"""
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runner.poll import UPSTREAM, github  # noqa: E402

AREAS = ("frontend", "auth", "postgres", "self-hosted", "documentation", "other")
OUT = ROOT / "baseline/timed.csv"


def main():
    done = set()
    if OUT.exists():
        done = {row["issue_number"] for row in csv.DictReader(OUT.open())}
    else:
        OUT.write_text("issue_number,seconds,area\n")
    with open(ROOT / "golden/v1/dev_truth.csv") as f:
        todo = [row["issue_number"] for row in csv.DictReader(f) if row["issue_number"] not in done]
    for number in todo[:15 - len(done)]:
        it = github(f"{UPSTREAM}/{number}", os.environ["PREREG_READ_TOKEN"])[1]
        print(f"\n{'=' * 80}\n{it['title']}\n\n{(it['body'] or '')[:3000]}\n")
        start = time.monotonic()
        area = ""
        while area not in AREAS + ("q",):
            area = input(f"area ({', '.join(AREAS)}), or q: ").strip().lower()
        if area == "q":
            break
        with OUT.open("a") as f:
            f.write(f"{number},{time.monotonic() - start:.0f},{area}\n")
    n = sum(1 for _ in csv.DictReader(OUT.open()))
    print(f"{n} of 15 decisions timed in {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
