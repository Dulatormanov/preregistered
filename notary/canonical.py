r"""Canonical format v1. Never edit the v1 rules: add v2 next to them.

Anyone can recompute every hash from the revealed guesses and the Notary log with these rules.
Each hash is the lowercase hex SHA-256 of UTF-8 text.
- content_sha256(title, body) = hash of title + "\n\n" + body; a missing title or body is "".
- row_text(p) = JSON of the 8 FIELDS: keys sorted, no spaces, non-ASCII escaped,
  created_at in UTC as YYYY-MM-DDTHH:MM:SS.ffffffZ.
- rows_digest(rows) = hash of the row texts joined by "\n", in id order.
- anchor_text(rows) = "canon=v1 kind=rows upto=<last id> n=<count> rows=<rows_digest>". It covers every guess
  with an id above the upto of the previous kind=rows anchor (0 for the first), up to and including upto.
- chain(prev, text) = hash of prev + "\n" + text. prev is the chain of the previous anchor, of any kind;
  the first prev is GENESIS, 64 zeros.
- An anchor is a comment by github-actions[bot] on the Notary log: text + " chain=" + chain(prev, text).
  Other comments are not anchors.
- file_text(path, sha256, commit) = "canon=v1 kind=file file=<path> sha256=<hash of the file's bytes>
  commit=<40-hex git commit>": one file of this repo, as it was at that commit. The path uses only
  A-Z a-z 0-9 . _ - and /. Added on 2026-11-04, before the first file anchor; nothing above changes.
"""
import hashlib
import json
import re
from datetime import timezone

CANON = "v1"
GENESIS = "0" * 64
FIELDS = ("id", "issue_number", "champion_id", "trial", "area", "needs_details", "input_sha256", "created_at")
FILE_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")


def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def content_sha256(title, body):
    return sha256((title or "") + "\n\n" + (body or ""))


def row_text(p):
    d = {k: p[k] for k in FIELDS}
    d["created_at"] = p["created_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def rows_digest(rows):
    return sha256("\n".join(row_text(p) for p in rows))


def anchor_text(rows):
    return f"canon={CANON} kind=rows upto={rows[-1]['id']} n={len(rows)} rows={rows_digest(rows)}"


def chain(prev, text):
    return sha256(prev + "\n" + text)


def file_text(path, file_sha256, commit):
    if not FILE_PATH.fullmatch(path) or ".." in path.split("/"):
        raise ValueError("file anchors take a plain path inside the repo")
    if not (re.fullmatch(r"[0-9a-f]{64}", file_sha256) and re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise ValueError("file anchors take a sha256 and a 40-hex commit")
    return f"canon={CANON} kind=file file={path} sha256={file_sha256} commit={commit}"
