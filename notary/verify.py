"""Verify the Notary log from public data only (Build day 8): the revealed guesses and anchors on the data branch,
the anchored files in git, and the comments on issue 1. Anyone can run it from a clean clone with a read-only token.

  GH_TOKEN=... python -m notary.verify DATA_DIR
For every anchor, in order:
- it is a comment on issue 1 by the github-actions bot (GraphQL author: Bot github-actions), never edited, and its
  text and chain equal the published anchor;
- its chain links to the anchor before it (the first to GENESIS);
- a rows anchor recomputes from the revealed rows it covers; if they are not all revealed yet (under 14 days old),
  it is "waiting", which is not a failure;
- a file anchor matches the file in git at its commit.
No anchor may be missing: the published list and the bot's comments must be the same, one for one.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from notary.canonical import GENESIS, chain, file_text, sha256

ROOT = Path(__file__).resolve().parents[1]
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


def verify(lines, anchors, comments, git_show=git_file):
    """(problems, report lines). lines: the revealed row texts; anchors: the published anchor rows."""
    rows = {json.loads(line)["id"]: line for line in lines}
    bot = [c for c in comments if (c.get("author") or {}).get("__typename") == "Bot"
           and c["author"]["login"] == "github-actions"]
    problems, report, prev, low = [], [], GENESIS, 0
    if [a["comment_id"] for a in anchors] != [c["databaseId"] for c in bot]:
        problems.append(f"{len(anchors)} published anchors, but {len(bot)} anchor comments by the bot")
    for a, c in zip(anchors, bot):
        text, _, head = c["body"].rpartition(" chain=")
        if c.get("lastEditedAt"):
            problems.append(f"anchor {a['id']}: the comment was edited")
        if (text, head) != (a["text"], a["chain_hash"]) or head != chain(prev, text):
            problems.append(f"anchor {a['id']}: its text or chain does not match, or does not link to the one before")
        if " kind=rows " in f" {text} ":
            upto = int(text.split(" upto=")[1].split()[0])
            covered = [rows.get(i) for i in range(low + 1, upto + 1)]
            if None in covered:
                report.append(f"anchor {a['id']}: waiting for the reveal of guesses {low + 1} to {upto}")
            elif text.split(" rows=")[1] != sha256("\n".join(covered)) or f" n={len(covered)} " not in f" {text} ":
                problems.append(f"anchor {a['id']}: the revealed guesses {low + 1} to {upto} do not recompute")
            else:
                report.append(f"anchor {a['id']}: guesses {low + 1} to {upto} recompute")
            low = upto
        else:
            f = dict(kv.split("=", 1) for kv in text.split()[2:])
            ok = text == file_text(f["file"], hashlib.sha256(git_show(f["commit"], f["file"])).hexdigest(), f["commit"])
            (report if ok else problems).append(f"anchor {a['id']}: {f['file']} at {f['commit'][:7]}"
                                                + (" matches git" if ok else " does not match git"))
        prev = head
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
