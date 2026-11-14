"""Verify the Notary log from public data only (Build day 8): the revealed guesses and anchors on the data branch,
the anchored files in git, and the comments on issue 1. Anyone can run it from a clean clone with a read-only token.

  GH_TOKEN=... python -m notary.verify DATA_DIR
For every anchor, in order:
- it is a comment on issue 1 by the github-actions bot (GraphQL author: Bot github-actions), never edited, and its
  text and chain equal the published anchor;
- its chain links to the anchor before it (the first to GENESIS);
- a rows anchor recomputes from the revealed rows in its id range: exactly n= of them, so an id the database
  skipped is not a gap. If fewer are revealed while the anchor is under 9 days old (the reveal publishes rows
  7 days old, daily, and may miss a run), it is "waiting", which is not a failure; after that it is a problem;
- a file anchor matches the file in git at its commit.
No anchor may be missing: the published list and the bot's first comments must be the same, one for one. A bot
comment newer than the last reveal is reported, and is a problem only once it is 2 days old (the reveal publishes
every anchor daily, and may miss a run). No revealed row may repeat an id, or lie outside every rows anchor's range.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from notary.canonical import GENESIS, chain, file_text, sha256

ROOT = Path(__file__).resolve().parents[1]
REVEAL_DAYS = 9  # every row of an anchor is revealed by then (v1: 16)
PUBLISH_DAYS = 2  # every anchor comment is on the data branch by then
QUERY = """query($cursor: String) { repository(owner: "Dulatormanov", name: "preregistered") { issue(number: 1) {
  comments(first: 100, after: $cursor) { pageInfo { hasNextPage endCursor }
    nodes { databaseId body createdAt lastEditedAt author { __typename login } } } } } }"""


def notary_comments(token):
    """Every comment on the Notary log, with its author's type and whether it was ever edited."""
    out, cursor = [], None
    while True:
        req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps(
            {"query": QUERY, "variables": {"cursor": cursor}}).encode(),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "preregistered"})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = json.load(r)["data"]["repository"]["issue"]["comments"]
        out += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        cursor = page["pageInfo"]["endCursor"]


def git_file(commit, path):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{path}"], capture_output=True, check=True).stdout


def verify(lines, anchors, comments, git_show=git_file, now=None):
    """(problems, report lines). lines: the revealed row texts; anchors: the published anchor rows."""
    now = now or datetime.now(timezone.utc)
    ids = [json.loads(line)["id"] for line in lines]
    rows = dict(zip(ids, lines))
    bot = [c for c in comments if (c.get("author") or {}).get("__typename") == "Bot"
           and c["author"]["login"] == "github-actions"]
    problems, report, prev, low = [], [], GENESIS, 0
    age = lambda c: (now - datetime.fromisoformat(c["createdAt"].replace("Z", "+00:00"))).days  # noqa: E731
    problems += [f"guess {i} is revealed {k} times" for i, k in sorted(Counter(ids).items()) if k > 1]
    if [a["comment_id"] for a in anchors] != [c["databaseId"] for c in bot[:len(anchors)]]:
        problems.append(f"{len(anchors)} published anchors, but the bot's first {len(anchors)} anchor comments differ")
    newer = bot[len(anchors):]  # posted after the last reveal, so the next one publishes them
    if any(age(c) >= PUBLISH_DAYS for c in newer):
        problems.append(f"an anchor comment is {PUBLISH_DAYS} or more days old and not on the data branch")
    elif newer:
        report.append(f"{len(newer)} newer anchor comments: posted after the last reveal, published by the next")
    for a, c in zip(anchors, bot):
        text, _, head = c["body"].rpartition(" chain=")
        if c.get("lastEditedAt"):
            problems.append(f"anchor {a['id']}: the comment was edited")
        if (text, head) != (a["text"], a["chain_hash"]) or head != chain(prev, text):
            problems.append(f"anchor {a['id']}: its text or chain does not match, or does not link to the one before")
        if " kind=rows " in f" {text} ":
            upto, n = (int(text.split(f" {k}=")[1].split()[0]) for k in ("upto", "n"))
            covered = [rows[i] for i in sorted(rows) if low < i <= upto]
            if len(covered) == n and text.split(" rows=")[1] == sha256("\n".join(covered)):
                report.append(f"anchor {a['id']}: its {n} guesses, ids {low + 1} to {upto}, recompute")
            elif len(covered) < n and age(c) < REVEAL_DAYS:
                report.append(f"anchor {a['id']}: waiting for the reveal of guesses {low + 1} to {upto}")
            else:
                problems.append(f"anchor {a['id']}: {len(covered)} of its {n} guesses, ids {low + 1} to {upto}, are"
                                f" revealed {age(c)} days after it, and they do not recompute")
            low = upto
        else:
            f = dict(kv.split("=", 1) for kv in text.split()[2:])
            ok = text == file_text(f["file"], hashlib.sha256(git_show(f["commit"], f["file"])).hexdigest(), f["commit"])
            (report if ok else problems).append(f"anchor {a['id']}: {f['file']} at {f['commit'][:7]}"
                                                + (" matches git" if ok else " does not match git"))
        prev = head
    outside = [i for i in rows if i <= 0 or i > low]
    if outside:
        problems.append(f"{len(outside)} revealed guesses lie outside every rows anchor")
    return problems, report


def main():
    data = Path(sys.argv[1])
    lines = (data / "guesses.jsonl").read_text().splitlines()
    anchors = [json.loads(line) for line in (data / "anchors.jsonl").read_text().splitlines()]
    problems, report = verify(lines, anchors, notary_comments(os.environ["GH_TOKEN"]))
    print("\n".join(report))
    print("\n".join(f"PROBLEM {p}" for p in problems) or f"verify: all {len(anchors)} anchors hold")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
