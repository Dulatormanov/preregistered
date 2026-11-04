"""Post the chain hash of every guess not yet anchored, and of a file if asked, on the pinned Notary log.

This job holds an issues:write token for this repo (GitHub has no comment-only
permission), so it runs nothing but this file. It logs in as notary, which may add anchors and
nothing else. The connection is in autocommit mode: no transaction is open during a network call.
"""
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from notary.canonical import FIELDS, FILE_PATH, GENESIS, anchor_text, chain, file_text
from scripts.lint_refs import check as lint_refs

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
    db.execute("select prereg.record_anchor(%s, %s, %s, %s, %s)",  # notary may add anchors only this way
               [text, head, int(upto[1]) if upto else None, comment["id"], utc(comment["created_at"])])


def post(db, prev, text):
    if lint_refs(text):  # every posted text passes the reference lint first
        raise SystemExit("anchor text failed the reference lint")
    head = chain(prev, text)
    record(db, text, head, comments("POST", body={"body": f"{text} chain={head}"}))  # a lost record heals next run
    return head


def main():
    with psycopg.connect(os.environ["NOTARY_DB_URL"], row_factory=dict_row, autocommit=True) as db:
        last = db.execute(
            "select chain_hash, comment_created_at from prereg.anchors order by id desc limit 1").fetchone()
        prev = last["chain_hash"] if last else GENESIS
        # A run may have posted an anchor and then lost its record (a lost response, a dropped
        # connection). Record such comments first, so the public chain never forks or repeats.
        since = (last["comment_created_at"] if last else LEDGER_START).astimezone(timezone.utc)
        # note: one page of 100 comments; lock the issue if strangers ever flood it
        healed = 0
        for c in comments("GET", f"?per_page=100&since={since:%Y-%m-%dT%H:%M:%SZ}"):
            text, _, head = (c.get("body") or "").rpartition(" chain=")
            if (c.get("user") or {}).get("login") == "github-actions[bot]" and head == chain(prev, text):
                record(db, text, head, c)
                prev = head
                healed += 1
        done = [f"healed={healed}"] if healed else []
        upto = db.execute("select coalesce(max(upto_prediction_id), 0) as n from prereg.anchors").fetchone()["n"]
        rows = db.execute(f"select {', '.join(FIELDS)} from prereg.predictions where id > %s order by id",
                          [upto]).fetchall()
        if rows:
            prev = post(db, prev, anchor_text(rows))
            done.append(f"rows n={len(rows)}")
        path = os.environ.get("ANCHOR_FILE", "").strip()
        if path:  # workflow_dispatch input: a file of this repo, pinned at this run's commit
            if not FILE_PATH.fullmatch(path):
                raise SystemExit("ANCHOR_FILE must be a plain path inside the repo")
            subprocess.run(["git", "ls-files", "--error-unmatch", "--", path], check=True, capture_output=True)
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            prev = post(db, prev, file_text(path, digest, os.environ["GITHUB_SHA"]))
            done.append(f"file={path}")
    print(f"anchored {' '.join(done)} chain={prev}" if done else "anchor: nothing new")


if __name__ == "__main__":
    main()
