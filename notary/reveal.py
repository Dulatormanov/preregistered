"""The rolling reveal (Build day 8): every day, each guess saved 7 or more days ago goes public on the data branch,
so anyone can recompute every anchor from it with notary/verify.py. By then the issue's labels are in, so a published
guess cannot help anyone label: a label counts only within 7 days (deviation 1 in DEVIATIONS.md; v1 had 14 for both).
Until then a guess is public only as part of an anchor's hash.

  OBSERVER_DB_URL=... python -m notary.reveal OUT_DIR
It writes OUT_DIR/guesses.jsonl (one canonical row per line, notary/canonical.py's row_text, in id order) and
OUT_DIR/anchors.jsonl (every anchor: id, text, chain, comment id and GitHub time). Never issue text or a login.
"""
import json
import os
import sys
from pathlib import Path

from notary.canonical import FIELDS, row_text

AGE_DAYS = 7


def main():
    import psycopg
    from psycopg.rows import dict_row
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["OBSERVER_DB_URL"], autocommit=True, row_factory=dict_row) as db:  # reads only
        rows = db.execute(f"select {', '.join(FIELDS)} from prereg.predictions"
                          f" where created_at <= now() - interval '{AGE_DAYS} days' order by id").fetchall()
        anchors = db.execute("select id, text, chain_hash, upto_prediction_id, comment_id, comment_created_at"
                             " from prereg.anchors order by id").fetchall()
    (out / "guesses.jsonl").write_text("".join(row_text(r) + "\n" for r in rows))
    (out / "anchors.jsonl").write_text("".join(json.dumps(
        {**a, "comment_created_at": a["comment_created_at"].strftime("%Y-%m-%dT%H:%M:%SZ")}, sort_keys=True) + "\n"
        for a in anchors))
    print(f"reveal: {len(rows)} guesses at least {AGE_DAYS} days old, {len(anchors)} anchors")


if __name__ == "__main__":
    main()
