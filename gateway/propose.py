"""The plan job of promote.yml (Build day 6): it chooses the day's one bundle, saves its exact bytes and their hash,
and prints the first 12 characters of the hash, which the owner's approval must quote.

  PROPOSER_DB_URL=... ANTHROPIC_API_KEY=... GH_TOKEN=... python -m gateway.propose
The target is one of the synthetic sandbox issues (sandbox/targets.toml) that carries no area label yet, one a day in
turn, and the label is the champion's guess for its text, made now through core/models.py (job gate). A label, once
written, stays: each target can be promoted once.
- If the sealed score promoted an area (results/sealed.json), only a promoted area that is not demoted may be
  proposed. Demoted means: the upper end of its live 95% Wilson interval is below 0.70 (PREREGISTRATION.md v1).
- If no area is promoted, the bundle is synthetic, and says so.
It proposes nothing if the label is not allowed, or if today already has a bundle.
"""
import hashlib
import json
import os
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def choose(targets, today, labelled=frozenset()):
    """The day's target, in turn, among the targets that carry no area label yet; None when all are used."""
    free = [t for t in targets if t["issue"] not in labelled]
    return free[today.toordinal() % len(free)] if free else None


def demoted(counts, area):
    """True if the area's live record is so poor that the upper end of its Wilson interval is below 0.70."""
    from adopt.stats import wilson
    guessed, correct = counts.get(area, (0, 0))
    return guessed > 0 and wilson(correct, guessed)[1] < 0.70


def main():
    import anthropic
    import psycopg
    from psycopg.types.json import Jsonb
    from agents import champion
    from core import models
    from gateway.payload import canonical
    from runner.poll import github
    sealed = ROOT / "results/sealed.json"
    promoted = json.loads(sealed.read_text())["promoted"] if sealed.exists() else []
    from gateway.gateway import AREAS
    targets = tomllib.loads((ROOT / "sandbox/targets.toml").read_text())["target"]
    issues = {t["issue"]: github(f"https://api.github.com/repos/Dulatormanov/prereg-sandbox/issues/{t['issue']}",
                                 os.environ["GH_TOKEN"])[1] for t in targets}
    labelled = {n for n, it in issues.items() if any(lab["name"] in AREAS for lab in it["labels"])}
    target = choose(targets, date.today(), labelled)
    if target is None:
        print("propose: no bundle today: every synthetic target already has its label; open new ones in sandbox/targets.toml")
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("consent_id=\nhash12=\n")
        return
    it = issues[target["issue"]]
    cfg = champion.load()
    consent_id = None
    with psycopg.connect(os.environ["PROPOSER_DB_URL"], autocommit=True) as db:  # proposer: functions only
        area, _, _, step = models.answer(db, "gate", cfg, anthropic.Anthropic(max_retries=2, timeout=60),
                                         it["title"], it["body"])
        db.execute("select prereg.record_gate_step('gate', null, %s)", [Jsonb(step)])
        counts = {a: (g, c) for a, g, c in db.execute("select * from prereg.area_live_counts()").fetchall()}
        why = None if area else "the champion gave no answer"
        if area and promoted and (area not in promoted or demoted(counts, area)):
            why = f"the champion's guess, {area}, is not a promoted area that is still above the bar"
        if why is None:
            payload = canonical(target["issue"], area)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            bundle = {"issue": target["issue"], "label": area, "champion": cfg["c"]["id"], "synthetic": not promoted,
                      "why": "synthetic: no area has passed the sealed bar yet" if not promoted else "a promoted area"}
            try:
                consent_id = db.execute("select prereg.propose_bundle(%s, %s, %s)", [Jsonb(bundle), payload, digest]).fetchone()[0]
                db.execute("select prereg.spend_contact('approval_request', '')")  # the day's one approval request
            except psycopg.errors.UniqueViolation:
                why = "today already has a bundle"
    if consent_id:
        print(f"propose: bundle {consent_id}: add the label {area} to sandbox issue {target['issue']}"
              f"{' (synthetic)' if not promoted else ''}. To approve, quote this in the approval comment: {digest[:12]}")
    else:
        print(f"propose: no bundle today: {why}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"consent_id={consent_id or ''}\nhash12={digest[:12] if consent_id else ''}\n")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
