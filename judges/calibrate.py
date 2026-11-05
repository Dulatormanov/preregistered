"""Calibrate the judge on hand labels, and write its card (Build day 3). The questions, the labels and the judge's
verdicts stay in golden/private/judge.sqlite (git-ignored); judges/card.md holds counts and rates only.

  python -m judges.calibrate make    write 60 reporter questions for dev-set issues that lacked details:
                                     40 with the agent's prompt, 20 deliberately generic, in a hidden mix
  python -m judges.calibrate label   label each one good or bad, by hand, without seeing how it was made
  python -m judges.calibrate card    run the judge on the 30 held-out labels, and write judges/card.md
make and card call Claude as job 'gate' (its $12 a day cap) and need GATE_DB_URL, ANTHROPIC_API_KEY and a GitHub
token in PREREG_READ_TOKEN. The judge is gating only if both its true-positive and its true-negative rate on the
held-out labels are at least 0.90 (PREREGISTRATION.md v1); otherwise it is advisory.
"""
import hashlib
import json
import os
import sqlite3
import sys
import urllib.error
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "golden/private/judge.sqlite"
CARD = ROOT / "judges/card.md"
BAR = 0.90


def private():
    db = sqlite3.connect(DB)
    db.execute("create table if not exists questions (issue_number integer primary key, split text, kind text,"
               " question text, broken text, human text, judge text)")
    return db


def issue_text(number):
    from runner.poll import UPSTREAM, github
    it = github(f"{UPSTREAM}/{number}", os.environ["PREREG_READ_TOKEN"])[1]
    return it["title"], it["body"]


def ledger():
    import psycopg
    return psycopg.connect(os.environ["GATE_DB_URL"], autocommit=True)


def call(gate, fn, *args):
    """Run one paid call under the gate's cap, and save its step."""
    from psycopg.types.json import Jsonb
    from core import models
    used, cap = models.spent(gate, "gate")
    if used >= cap:
        raise models.OverCap(f"job gate has spent ${used} of its ${cap} cap")
    result, step = fn(*args)
    gate.execute("select prereg.record_gate_step('gate', null, %s)", [Jsonb(step)])
    return result


def make():
    import anthropic
    from agents import champion, question
    from golden.truth import SEALED_FROM, truth
    rows = [json.loads(line) for line in (ROOT / "golden/private/issues.jsonl").read_text().splitlines()]
    lacking = [r["number"] for r in rows if r["created_at"][:10] < SEALED_FROM.isoformat() and truth(r)[1]]
    picked = sorted(lacking, key=lambda n: hashlib.sha256(f"judge:{n}".encode()).hexdigest())[:66]  # spares
    cfg, client, db = champion.load(), anthropic.Anthropic(max_retries=2, timeout=60), private()
    with ledger() as gate:
        for i, n in enumerate(picked):
            if db.execute("select count(*) from questions").fetchone()[0] >= 60:
                break
            if db.execute("select 1 from questions where issue_number = ?", [n]).fetchone():
                continue
            lazy = i % 3 == 2  # every third one is generic
            try:
                text = issue_text(n)
            except urllib.error.HTTPError:  # deleted or moved since the golden set: skip it
                continue
            q = call(gate, question.ask, cfg, client, *text, lazy) or ""
            db.execute("insert into questions values (?, ?, ?, ?, ?, null, null)",
                       [n, "build" if i % 2 == 0 else "held_out", "lazy" if lazy else "prompt", q,
                        json.dumps(question.checks(q))])
            db.commit()
    print(f"{db.execute('select count(*) from questions').fetchone()[0]} questions in {DB.relative_to(ROOT)}")


def label():
    db = private()
    for n, q in db.execute("select issue_number, question from questions where human is null order by split desc,"
                           " issue_number").fetchall():  # the 30 held-out ones first: the card needs only those
        title, body = issue_text(n)
        print(f"\n{'=' * 80}\n{title}\n\n{(body or '')[:1200]}\n\nQUESTION: {q}")
        answer = input("good question? [y]es, [n]o, [q]uit: ").strip().lower()
        if answer == "q":
            break
        if answer in ("y", "n"):
            db.execute("update questions set human = ? where issue_number = ?", ["good" if answer == "y" else "bad", n])
            db.commit()
    held = db.execute("select count(*) from questions where human is not null and split = 'held_out'").fetchone()[0]
    print(f"{db.execute('select count(*) from questions where human is not null').fetchone()[0]} of 60 labelled;"
          f" {held} of the 30 held-out ones, which are all the card needs")


def rates(pairs):
    """(true-positive rate, true-negative rate, counts) from (human, judge) pairs; a rate is None with no cases."""
    good = [j for h, j in pairs if h == "good"]
    bad = [j for h, j in pairs if h == "bad"]
    tpr = sum(j == "good" for j in good) / len(good) if good else None
    tnr = sum(j == "bad" for j in bad) / len(bad) if bad else None
    return tpr, tnr, {"good": len(good), "bad": len(bad)}


def verdict(tpr, tnr):
    return "gating" if tpr is not None and tnr is not None and tpr >= BAR and tnr >= BAR else "advisory"


def card():
    import anthropic
    from agents import champion
    from judges.judge import RUBRIC, judge
    cfg, client, db = champion.load(), anthropic.Anthropic(max_retries=2, timeout=60), private()
    held = db.execute("select issue_number, question, human from questions where split = 'held_out'"
                      " and human is not null").fetchall()
    if len(held) < 30:
        sys.exit(f"only {len(held)} of the 30 held-out questions are labelled: run label first")
    with ledger() as gate:
        for n, q, _ in held:
            db.execute("update questions set judge = ? where issue_number = ?", [call(gate, judge, cfg, client, *issue_text(n), q), n])
            db.commit()
    pairs = db.execute("select human, judge from questions where split = 'held_out' and human is not null").fetchall()
    tpr, tnr, counts = rates(pairs)
    fmt = lambda x: "none (no such labels)" if x is None else f"{x:.2f}"  # noqa: E731
    CARD.write_text(f"""Independent project, not affiliated with Supabase.

# The judge's card

- **Verdict: {verdict(tpr, tnr)}.** The rule (PREREGISTRATION.md v1): gating only if the true-positive rate and
  the true-negative rate on the 30 held-out hand labels are both at least {BAR:.2f}.
- **Held-out labels:** {counts['good']} good and {counts['bad']} bad questions, labelled by hand before the judge saw them.
- **True-positive rate** (the judge says good when the label says good): {fmt(tpr)}.
- **True-negative rate** (the judge says bad when the label says bad): {fmt(tnr)}.
- **Judge:** {cfg['c']['model']}, effort low, thinking off; rubric `judges/rubric.md`, SHA-256
  `{hashlib.sha256(RUBRIC.encode()).hexdigest()}`.
- **Made on** {date.today().isoformat()}. The questions, the labels and the judge's answers stay in the private
  database, so this card holds counts and rates only.
""")
    print(CARD.read_text())


if __name__ == "__main__":
    {"make": make, "label": label, "card": card}[sys.argv[1]]()
