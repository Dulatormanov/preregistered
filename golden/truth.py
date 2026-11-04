"""The truth for one issue, under rules/ground_truth.toml (or one switch changed, for the sensitivity table).

The area is the area of the first counting label: a label that maps to an area, added within window_days of
the issue's creation, by a human who is not the issue's author (by default). needs_details is true if the
awaiting-details label was added the same way. An issue with no counting area label is not scorable.
Run python golden/truth.py to check it: dev-set counts are printed (and golden/v1/dev_truth.csv is written, the
triage suite's samples), and the sealed set prints only
"enough" or "not enough" per area (Check 12), so nobody sees its labels before it is scored once.
"""
import json
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = tomllib.loads((ROOT / "rules/ground_truth.toml").read_text())
SEALED_FROM = date(2026, 9, 20)
ENOUGH = 15  # the promotion bar needs a label guessed on at least 15 sealed issues


def counts_for(event, rules):
    if event["action"] != "add" or event["after_s"] > rules["window_days"] * 86400:
        return False
    if event["actor"] != "User" and rules["agent_labels"] == "out":
        return False
    return not (event["by_author"] and rules["template_labels"] == "out")


def area_of(label, rules):
    for area, labels in rules["areas"].items():
        if label in labels:
            return area if area != "other" or rules["pool_rare"] else None
    return None


def truth(issue, rules=RULES):
    """(area or None, needs_details) for one golden-set row."""
    events = sorted((e for e in issue["label_events"] if counts_for(e, rules)), key=lambda e: e["after_s"])
    area = next((a for e in events if (a := area_of(e["label"], rules))), None)
    return area, any(e["label"] == rules["needs_details_label"] for e in events)


def main():
    rows = [json.loads(line) for line in (ROOT / "golden/private/issues.jsonl").read_text().splitlines()]
    dev = [r for r in rows if date.fromisoformat(r["created_at"][:10]) < SEALED_FROM]
    sealed = [r for r in rows if date.fromisoformat(r["created_at"][:10]) >= SEALED_FROM]
    areas = list(RULES["areas"])
    dev_truth = [truth(r) for r in dev]
    counts = {"issues": len(dev), "scorable": sum(a is not None for a, _ in dev_truth),
              "areas": {a: sum(t == a for t, _ in dev_truth) for a in areas},
              "needs_details": sum(nd for _, nd in dev_truth), "rules_version": RULES["version"]}
    (ROOT / "golden/v1/dev_counts.json").write_text(json.dumps(counts, indent=1) + "\n")
    # The triage suite's samples: the scorable dev issues, with no label times (they show how fast maintainers work).
    (ROOT / "golden/v1/dev_truth.csv").write_text("issue_number,content_sha256,area,needs_details\n" + "".join(
        f"{r['number']},{r['content_sha256']},{a},{str(nd).lower()}\n"
        for r, (a, nd) in sorted(zip(dev, dev_truth), key=lambda x: x[0]["number"]) if a is not None))
    print("dev set:", json.dumps(counts))
    sealed_areas = [truth(r)[0] for r in sealed]
    print("Check 12 (sealed set, labels not final until 2026-11-14):",
          ", ".join(f"{a}: {'enough' if sealed_areas.count(a) >= ENOUGH else 'not enough'}" for a in areas))


if __name__ == "__main__":
    main()
