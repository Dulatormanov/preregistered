"""Post the chain hash of every guess not yet anchored, on the pinned Notary log issue.

This job holds an issues:write token for this repo (GitHub has no comment-only
permission), so it runs nothing but this file.
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from notary.canonical import FIELDS, GENESIS, anchor_text, chain

LEDGER_START = datetime(2026, 11, 3, tzinfo=timezone.utc)  # the same day as START in runner/poll.py


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def comments(method, query="", body=None):
    """GET or POST comments on the Notary log."""
    url = (f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}"
           f"/issues/{os.environ['NOTARY_ISSUE']}/comments{query}")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "preregistered"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def record(db, text, head, comment):
    upto = re.search(r" upto=(\d+) ", text)
    db.execute(
        "insert into prereg.anchors (text, chain_hash, upto_prediction_id, comment_id, comment_created_at)"
        " values (%s, %s, %s, %s, %s)",
        [text, head, int(upto[1]) if upto else None, comment["id"], utc(comment["created_at"])])


def main():
    with psycopg.connect(os.environ["TRIAGE_DB_URL"], row_factory=dict_row) as db:
        last = db.execute(
            "select chain_hash, comment_created_at from prereg.anchors order by id desc limit 1").fetchone()
        prev = last["chain_hash"] if last else GENESIS
        # A run may have posted an anchor and then lost its record (a lost response, a dropped
        # connection). Record such comments first, so the public chain never forks or repeats.
        since = (last["comment_created_at"] if last else LEDGER_START).astimezone(timezone.utc)
        # note: one page of 100 comments; lock the issue if strangers ever flood it
        for c in comments("GET", f"?per_page=100&since={since:%Y-%m-%dT%H:%M:%SZ}"):
            text, _, head = (c.get("body") or "").rpartition(" chain=")
            if (c.get("user") or {}).get("login") == "github-actions[bot]" and head == chain(prev, text):
                record(db, text, head, c)
                prev = head
        upto = db.execute("select coalesce(max(upto_prediction_id), 0) as n from prereg.anchors").fetchone()["n"]
        rows = db.execute(f"select {', '.join(FIELDS)} from prereg.predictions where id > %s order by id",
                          [upto]).fetchall()
        if not rows:
            print("anchor: nothing new")
            return
        text = anchor_text(rows)
        head = chain(prev, text)
        record(db, text, head, comments("POST", body={"body": f"{text} chain={head}"}))
    print(f"anchored n={len(rows)} chain={head}")


if __name__ == "__main__":
    main()
