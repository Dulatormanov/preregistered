"""One model check (Build day 4): a challenger against the incumbent, with the champion's prompt and settings.

  ADOPTER_DB_URL=... ANTHROPIC_API_KEY=... PREREG_READ_TOKEN=... python -m adopt.check MODEL
  ... --dry-run   the champion's own model against rules_v0 on the 186 dev-set issues; not a paid check
A real check needs the sealed run: the challenger guesses the 20 safety cases (3 trials each) and the scorable
sealed issues (trial 1), against the champion's sealed guesses. Its live series comes from a shadow run that is not
built yet, so a real check is INCONCLUSIVE at best until it is (the ADOPT rule needs 5 live issues).
Every call goes through core/models.py as job check:<model>, under its $10 cap; a model with no price in
prices.toml is SKIPPED, because its cap could not be kept. It writes results/verdicts/<check_id>.md and .json and
the verdict row. Counts only, never an issue number or text.
"""
import csv
import json
import os
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/verdicts"


def challenger(cfg, model):
    prices = tomllib.loads((ROOT / "prices.toml").read_text()).get(model)
    return {**cfg, "c": {**cfg["c"], "id": f"challenger-{model}", "model": model}, "prices": prices}


def compare(cases, incumbent, guesses):
    """(wins, losses): cases where exactly one is right, and it is the challenger, or the incumbent."""
    wins = sum(guesses.get(n) == truth != incumbent.get(n) for n, truth in cases.items())
    losses = sum(incumbent.get(n) == truth != guesses.get(n) for n, truth in cases.items())
    return wins, losses


def render(r):
    return f"""Independent project, not affiliated with Supabase.

# Model check: {r['model']}{' (dry run)' if r['dry_run'] else ''}

| | |
|---|---|
| Verdict | **{r['verdict']}**: {r['reason']} |
| Hours since the watcher first saw the model | {r['hours']} |
| Safety | {r['safety']} |
| Compared on | {r['set']} |
| Wins and losses | right where the {r['incumbent']} was wrong on {r['wins']} issues; the reverse on {r['losses']} |
| Sign test (one-sided) | p = {r['p']:.2g} |
| Live issues | {r['live']} |
| Cost | ${r['cost_per_100']} per 100 issues; ${r['cost']} for this check |

The rules are in PREREGISTRATION.md v1 (New models). This file holds counts only.
"""


def main():
    import anthropic
    import psycopg
    from psycopg.types.json import Jsonb
    from adopt import stats
    from agents import champion, guards, rules_v0
    from core import contracts, models
    from runner.poll import UPSTREAM, github
    from notary.canonical import content_sha256
    model, dry = sys.argv[1], "--dry-run" in sys.argv
    now = datetime.now(timezone.utc)
    check_id = f"{model}-{now:%Y%m%dT%H%M}" + ("-dry" if dry else "")
    cfg = champion.load()
    ch, job = challenger(cfg, model), f"check:{model}"
    client, cost, answered = anthropic.Anthropic(max_retries=2, timeout=60), 0.0, 0
    with psycopg.connect(os.environ["ADOPTER_DB_URL"], autocommit=True) as db:
        paid = 0 if dry else db.execute("select prereg.paid_checks()").fetchone()[0]
        first = db.execute("select prereg.model_first_seen(%s)", [model]).fetchone()[0]
        capped = ch["prices"] is None

        def ask(set_name, key, title, body):
            nonlocal cost, answered
            text, h, step = models.answer_raw(db, job, ch, client, title, body)
            db.execute("select prereg.record_gate_step(%s, null, %s)", [job, Jsonb(step)])
            cost += float(step["cost_usd"])
            ok = text is not None and not guards.check(text, cfg["areas"])
            answered += ok
            answer = json.loads(text) if ok else {}
            return text, h, step["status"], answer.get("area")

        safety_failed, n_safety = [], 0
        if not capped and (dry or paid < stats.MAX_PAID_CHECKS):
            if not dry:  # before any call: a real check needs every one of the champion's sealed rows
                from adopt.sealed import rows_of, sealed_list
                champion_rows, sealed = rows_of(db), sealed_list()
                if len(champion_rows) < len(sealed):
                    sys.exit("the sealed run is not complete yet: a real check needs the champion's sealed guesses")
            score = contracts.scorer("safety")
            for case in contracts.cases("safety"):
                for t in (1, 2, 3):
                    text, h, status, area = ask("safety", case["id"], case["title"], case["body"])
                    passed = score(text if area else None, case)[0] and status != "error"
                    db.execute("select prereg.record_challenger_guess(%s, %s, 'safety', %s, %s, %s, null, %s, %s)",
                               [check_id, model, f"{case['id']}:{t}", status, area, passed, h])
                    n_safety += 1
                    if not passed and case["id"] not in safety_failed:
                        safety_failed.append(case["id"])
            if dry:  # the dev set; the incumbent is rules_v0, run on the same text
                with open(ROOT / "golden/v1/dev_truth.csv") as f:
                    dev = [r for r in csv.DictReader(f)]
                cases, incumbent, guesses = {}, {}, {}
                for r in dev:
                    it = github(f"{UPSTREAM}/{r['issue_number']}", os.environ["PREREG_READ_TOKEN"])[1]
                    if content_sha256(it["title"], it["body"]) != r["content_sha256"]:
                        continue
                    n = int(r["issue_number"])
                    cases[n], incumbent[n] = r["area"], rules_v0.guess(it["title"], it["body"])[0]
                    _, h, status, guesses[n] = ask("dev", n, it["title"], it["body"])
                    db.execute("select prereg.record_challenger_guess(%s, %s, 'dev', %s, %s, %s, null, null, %s)",
                               [check_id, model, str(n), status, guesses[n], h])
                set_name, incumbent_name = f"the {len(cases)} dev-set issues (dry run)", "keyword baseline rules_v0"
            else:
                # The champion's answer per issue: an area, or None if it refused or answered invalidly (wrong).
                incumbent = {n: area for n, (status, area) in champion_rows.items() if status != "left_out"}
                from adopt.sealed import read
                from golden.truth import truth
                rows, numbers = {}, sorted(sealed)
                for i in range(0, len(numbers), 25):
                    rows.update(read(numbers[i:i + 25], os.environ["PREREG_READ_TOKEN"]))
                cases, guesses = {}, {}
                for n, row in rows.items():
                    area = truth(row)[0]
                    if area is None or row["content_sha256"] != sealed[n] or n not in incumbent:
                        continue
                    cases[n] = area
                    _, h, status, guesses[n] = ask("sealed", n, row["title"], row["body"])
                    db.execute("select prereg.record_challenger_guess(%s, %s, 'sealed', %s, %s, %s, null, null, %s)",
                               [check_id, model, str(n), status, guesses[n], h])
                set_name, incumbent_name = f"the {len(cases)} scorable sealed issues", f"champion {cfg['c']['id']}"
        else:
            cases, incumbent, guesses, set_name, incumbent_name = {}, {}, {}, "nothing (skipped)", "incumbent"
        wins, losses = compare(cases, incumbent, guesses)
        live_wins = live_losses = 0  # note: the shadow series on live issues is not built yet
        calls = n_safety + len(guesses)
        valid = answered > 0 or calls == 0  # SKIPPED only if the challenger gave no valid answer at all
        verdict, reason = stats.verdict(valid, capped, paid, not safety_failed, wins, losses, live_wins, live_losses,
                                        where="the dev set" if dry else "the sealed set")
        result = {"check_id": check_id, "model": model, "dry_run": dry, "verdict": verdict, "reason": reason,
                  "hours": round((now - first).total_seconds() / 3600, 1) if first else None,
                  "safety": (f"{20 - len(safety_failed)} of 20 cases passed all 3 trials" if n_safety else "not run"),
                  "set": set_name, "incumbent": incumbent_name, "wins": wins, "losses": losses,
                  "p": stats.sign_test(wins, losses), "live": f"{live_wins} of {live_wins + live_losses}",
                  "cost": round(cost, 4), "cost_per_100": round(100 * cost / calls, 4) if calls else None}
        db.execute("select prereg.record_verdict(%s, %s, %s, %s, %s)", [check_id, model, verdict, dry, Jsonb(result)])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{check_id}.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (OUT / f"{check_id}.md").write_text(render(result))
    print(f"check {check_id}: {verdict} ({reason}); wins {wins}, losses {losses}, cost ${result['cost']}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"check_id={check_id}\nverdict={verdict}\n")


if __name__ == "__main__":
    main()
