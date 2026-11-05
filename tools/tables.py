"""The sensitivity table (`make tables`): how much the agreement depends on the ground-truth rules.

  OBSERVER_DB_URL=... python tools/tables.py [results.jsonl]
Each row changes one switch of rules/ground_truth.toml; the first row is the pre-registered rule. Columns:
- the dev set: the champion's area in trial 1 of a suite run (results.jsonl, from suite.yml on main), against
  the label events in golden/private/issues.jsonl (git-ignored, so only the owner's machine has this column);
- the live window: the champion's counting guesses and the baseline's, against the outcomes in the ledger.
  A guess counts only if its anchor came before the first counting label (the time rule); coverage is the
  share of scorable issues that have a counting guess.
Counts and percentages only.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from golden.truth import RULES, counts_for, truth  # noqa: E402

CHAMPION = "haiku55-p2"  # named in PREREGISTRATION.md v1; a drill or ADOPT champion is a series of its own
WINDOW = (datetime(2026, 11, 14, tzinfo=timezone.utc), datetime(2026, 12, 5, tzinfo=timezone.utc))
VARIANTS = [("pre-registered rule", {}), ("labels within 7 days", {"window_days": 7}),
            ("labels within 28 days", {"window_days": 28}), ("the author's template labels count", {"template_labels": "in"}),
            ("bot and agent labels count", {"agent_labels": "in"}), ("rare areas dropped, not pooled", {"pool_rare": False})]


def score(guesses, rows, rules):
    """(scorable issues, with a counting guess, right) under one rule set."""
    scorable = have = right = 0
    for r in rows:
        area, _ = truth(r, rules)
        if area is None:
            continue
        scorable += 1
        guess = guesses.get(r["number"])
        if guess is not None and guess[1] < r.get("first_label_s", {}).get(json.dumps(rules, sort_keys=True), float("inf")):
            have += 1
            right += guess[0] == area
    return scorable, have, right


def cell(scorable, have, right, coverage=False):
    if not have:
        return f"{scorable} scorable, no counting guess yet" if scorable else "none scorable yet"
    text = f"{right / have:.1%} of {have}"
    return text + (f", coverage {have / scorable:.0%}" if coverage else "")


def dev(results):
    rows = [json.loads(line) for line in (ROOT / "golden/private/issues.jsonl").read_text().splitlines()]
    with open(results) as f:
        trials = [json.loads(line) for line in f]
    first = {}
    for t in trials:
        if t["eval"] == "triage" and t["run"] == 1 and t["trial"] == 1 and t.get("area"):
            first[int(t["case"])] = (t["area"], float("-inf"))  # the dev set is not live: no time rule
    return first, [r for r in rows if r["number"] in first]


def series_of(champion_id):
    return {"rules_v0": "baseline", CHAMPION: "champion"}.get(champion_id, champion_id)


def live(db):
    """{series: {number: (area, seconds after creation when its anchor posted)}}, and golden-style rows."""
    issues = db.execute("select issue_number, gh_created_at from prereg.issues_seen where gh_created_at >= %s"
                        " and gh_created_at < %s", list(WINDOW)).fetchall()
    events = db.execute("select issue_number, label, action, actor, by_author, labeled_at from prereg.outcomes").fetchall()
    guesses = db.execute(
        "select p.issue_number, p.champion_id, p.area, (select min(a.comment_created_at) from prereg.anchors a"
        " where a.upto_prediction_id >= p.id) from prereg.predictions p where p.trial = 1 order by p.id").fetchall()
    created = dict(issues)
    rows = [{"number": n, "label_events": [
        {"label": label, "action": action, "actor": actor, "by_author": by_author,
         "after_s": (at - created[n]).total_seconds()} for m, label, action, actor, by_author, at in events if m == n]}
        for n in created]
    for r in rows:  # the time rule: when the first counting label came, under each rule set
        r["first_label_s"] = {}
        for _, change in VARIANTS:
            rules = {**RULES, **change}
            counting = [e["after_s"] for e in r["label_events"] if counts_for(e, rules)]
            r["first_label_s"][json.dumps(rules, sort_keys=True)] = min(counting, default=float("inf"))
    series = {"champion": {}, "baseline": {}}
    for n, champion_id, area, anchored in guesses:
        if n in created and anchored is not None:
            series.setdefault(series_of(champion_id), {}).setdefault(n, (area, (anchored - created[n]).total_seconds()))
    return series, rows


def main():
    import psycopg
    results = sys.argv[1] if len(sys.argv) > 1 else None
    private = (ROOT / "golden/private/issues.jsonl").exists() and results
    dev_guesses, dev_rows = dev(results) if private else ({}, [])
    with psycopg.connect(os.environ["OBSERVER_DB_URL"], autocommit=True) as db:
        series, live_rows = live(db)
    print("| Ground-truth rule | Dev set, champion |" + "".join(f" Live window, {s} |" for s in series))
    print("|---|---|" + "---|" * len(series))
    for name, change in VARIANTS:
        rules = {**RULES, **change}
        d = cell(*score(dev_guesses, dev_rows, rules)) if private else "needs the private label events"
        print(f"| {name} | {d} |" + "".join(f" {cell(*score(gs, live_rows, rules), coverage=True)} |"
                                            for gs in series.values()))


if __name__ == "__main__":
    main()
