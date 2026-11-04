"""The sealed score (Build day 4): the champion named in PREREGISTRATION.md v1 guesses the 151 sealed issues once.

  ADOPTER_DB_URL=... ANTHROPIC_API_KEY=... PREREG_READ_TOKEN=... python -m adopt.sealed
1. It does nothing before 2026-11-16 00:00 UTC, when the sealed labels are final, or once sealed_guesses has rows.
2. It reads each sealed issue (title, body, creation time, label events) with GraphQL, and leaves out any issue
   whose text no longer has its hash in golden/v1/sealed_list.csv.
3. haiku55-p2 guesses each one, through core/models.py, as job check:sealed ($10 in all). Each guess goes to
   prereg.sealed_guesses, whose primary key makes a second run fail.
4. It writes results/sealed.json: per area, the true count, how often it was guessed and how often rightly, the
   Wilson low and whether it is promoted. Counts only, never an issue number or text.
"""
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL = datetime(2026, 11, 16, tzinfo=timezone.utc)
CHAMPION = "haiku55-p2"  # named in PREREGISTRATION.md v1
OUT = ROOT / "results/sealed.json"
FIELDS = ("number createdAt closedAt stateReason title body author { login } timelineItems(first: 100, itemTypes:"
          " [LABELED_EVENT, UNLABELED_EVENT]) { totalCount nodes { __typename ... on LabeledEvent { createdAt label"
          " { name } actor { __typename login } } ... on UnlabeledEvent { createdAt label { name } actor { __typename"
          " login } } } }")


def read(numbers, token):
    """Golden-set rows (golden/build.py's issue_row) with title and body, for a batch of issue numbers."""
    from golden.build import issue_row
    query = "{ repository(owner: \"supabase\", name: \"supabase\") {" + "".join(
        f" i{int(n)}: issue(number: {int(n)}) {{ {FIELDS} }}" for n in numbers) + " } }"
    req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps({"query": query}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": "preregistered"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if any(e.get("type") != "NOT_FOUND" for e in data.get("errors", [])) or not (data.get("data") or {}).get("repository"):
        raise SystemExit("the GraphQL read failed")  # never score on a partial read
    out = {}
    for it in data["data"]["repository"].values():
        if it:
            out[it["number"]] = {**issue_row(it), "title": it["title"], "body": it["body"]}
    return out


def summary(rows, guesses):
    """results/sealed.json: counts per area, under ground truth v1."""
    from adopt.stats import promoted, wilson
    from golden.truth import RULES, truth
    areas = {a: {"true": 0, "guessed": 0, "right": 0} for a in RULES["areas"]}
    scorable = right = answered = 0
    for n, row in rows.items():
        area, _ = truth(row)
        if area is None:
            continue
        scorable += 1
        areas[area]["true"] += 1
        guess = guesses.get(n)
        if guess:
            answered += 1
            areas[guess]["guessed"] += 1
            right += guess == area
            areas[guess]["right"] += guess == area
    for a in areas.values():
        a["wilson_low"] = round(wilson(a["right"], a["guessed"])[0], 4)
        a["promoted"] = promoted(a["guessed"], a["right"])
    return {"champion": CHAMPION, "scorable": scorable, "answered": answered, "right": right,
            "agreement": round(right / answered, 4) if answered else None, "areas": areas,
            "promoted": sorted(a for a, v in areas.items() if v["promoted"])}


def main(now=None):
    import anthropic
    import psycopg
    from psycopg.types.json import Jsonb
    from agents import champion
    from core import models
    now = now or datetime.now(timezone.utc)
    if now < FINAL:
        print(f"sealed: not before {FINAL:%Y-%m-%d %H:%M} UTC, when the sealed labels are final")
        return False
    cfg = champion.load()
    if cfg["c"]["id"] != CHAMPION:
        sys.exit(f"models.lock names {cfg['c']['id']}, but PREREGISTRATION.md v1 names {CHAMPION} for the sealed run")
    with open(ROOT / "golden/v1/sealed_list.csv") as f:
        sealed = {int(r["issue_number"]): r["content_sha256"] for r in csv.DictReader(f)}
    with psycopg.connect(os.environ["ADOPTER_DB_URL"], autocommit=True) as db:
        if db.execute("select prereg.sealed_count()").fetchone()[0]:
            print("sealed: already run once; it never runs again")
            return False
        numbers, rows = sorted(sealed), {}
        for i in range(0, len(numbers), 25):
            rows.update(read(numbers[i:i + 25], os.environ["PREREG_READ_TOKEN"]))
        kept = {n: r for n, r in rows.items() if r["content_sha256"] == sealed[n]}
        client, guesses = anthropic.Anthropic(max_retries=2, timeout=60), {}
        for n, r in sorted(kept.items()):
            area, needs_details, h, step = models.answer(db, "check:sealed", cfg, client, r["title"], r["body"])
            db.execute("select prereg.record_gate_step('check:sealed', %s, %s)", [n, Jsonb(step)])
            db.execute("select prereg.record_sealed_guess(%s, %s, %s, %s, %s, %s)",
                       [n, cfg["c"]["id"], step["status"], area, needs_details, h])
            if area:
                guesses[n] = area
    result = {**summary(kept, guesses), "run_at": now.isoformat(timespec="seconds"), "issues": len(sealed),
              "left_out": len(sealed) - len(kept), "rules": "rules/ground_truth.toml v1"}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"sealed: {result['answered']} of {result['scorable']} scorable issues answered, agreement"
          f" {result['agreement']}; promoted: {', '.join(result['promoted']) or 'none'}; left out {result['left_out']}")
    return True


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    ran = main()
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"ran={'yes' if ran else 'no'}\n")
