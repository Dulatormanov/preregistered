"""make tables-public: the live score from public data only (Build day 8). Anyone can run it from a clean clone with a
read-only token: the revealed guesses and anchors on the data branch, and the public label events of those issues.

  GH_TOKEN=... python tools/public_tables.py DATA_DIR
It applies the pre-registered rule (rules/ground_truth.toml v2) and the time rule (a guess counts only if its anchor
came before the first counting label), with the same scoring as make tables, and prints agreement and coverage per
series. Only guesses at least 7 days old are revealed, so the newest issues are not in it yet. Counts only.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from golden.truth import RULES, counts_for  # noqa: E402
from tools.tables import VARIANTS, WINDOW, cell, score, series_of  # noqa: E402


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    from adopt.sealed import read
    data = Path(sys.argv[1])
    guesses = [json.loads(line) for line in (data / "guesses.jsonl").read_text().splitlines()]
    anchors = [json.loads(line) for line in (data / "anchors.jsonl").read_text().splitlines()]
    rows_anchors = [a for a in anchors if a.get("upto_prediction_id")]
    numbers, rows = sorted({g["issue_number"] for g in guesses}), {}
    for i in range(0, len(numbers), 25):
        rows.update(read(numbers[i:i + 25], os.environ["GH_TOKEN"]))
    window = {n: r for n, r in rows.items() if WINDOW[0] <= utc(r["created_at"]) < WINDOW[1]}
    for r in window.values():  # the time rule, under each rule set: when the first counting label came
        r["first_label_s"] = {}
        for _, change in VARIANTS:
            rules = {**RULES, **change}
            r["first_label_s"][json.dumps(rules, sort_keys=True)] = min(
                (e["after_s"] for e in r["label_events"] if counts_for(e, rules)), default=float("inf"))
    series = {"champion": {}, "baseline": {}}
    for g in guesses:
        if g["issue_number"] not in window or g["trial"] != 1:
            continue
        anchored = min((utc(a["comment_created_at"]) for a in rows_anchors if a["upto_prediction_id"] >= g["id"]),
                       default=None)
        if anchored is not None:
            created = utc(window[g["issue_number"]]["created_at"])
            series.setdefault(series_of(g["champion_id"]), {}).setdefault(
                g["issue_number"], (g["area"], (anchored - created).total_seconds()))
    rules = dict(RULES)
    print("| Series | Live window, pre-registered rule |\n|---|---|")
    for name, gs in series.items():
        print(f"| {name} | {cell(*score(gs, list(window.values()), rules), coverage=True)} |")
    print(f"\nFrom {len(guesses)} revealed guesses; issues created {WINDOW[0]:%Y-%m-%d} to {WINDOW[1]:%Y-%m-%d}, UTC.")


if __name__ == "__main__":
    main()
