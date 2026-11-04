"""Rebuild one issue's guesses from public data, and check every step (Build day 3).

  OBSERVER_DB_URL=... python tools/reconstruct.py ISSUE_NUMBER
1. First sight: when the tick first saw the issue, and the content hash of its title and body then.
2. The text: the issue's current title and body on GitHub must still have that hash. If not, the public issue
   changed, and the run cannot be rebuilt from it, so it stops there.
3. The baseline: rules_v0, run again on that text, must give the saved guess.
4. The champion: its setup (the models.lock version, found in git by the SHA-256 its step saved), its steps
   (model, tokens, cost, request id), and every attempt (claimed, failed, finished), with its Actions run.
5. The anchor: the Notary log comment that covers the champion's guess, recomputed from the ledger's rows, with
   its chain link to the anchor before it, and its GitHub time against the first counting human label.
It prints hashes, counts and the issue number, never the issue's text. It returns False if any check fails.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents import champion, rules_v0  # noqa: E402
from notary.canonical import FIELDS, GENESIS, anchor_text, chain, content_sha256  # noqa: E402

REPO = "Dulatormanov/preregistered"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "preregistered", "Accept": "application/vnd.github+json"})
    if os.environ.get("GH_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GH_TOKEN']}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def lock_at(lock_sha256):
    """(commit, [champion] table) of the models.lock version with this SHA-256, from git history."""
    commits = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%H", "--", "models.lock"],
                             capture_output=True, text=True, check=True).stdout.split()
    for commit in commits:
        blob = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:models.lock"], capture_output=True,
                              check=True).stdout
        if hashlib.sha256(blob).hexdigest() == lock_sha256:
            import tomllib
            return commit, tomllib.loads(blob.decode())["champion"]
    return None, None


def reconstruct(db, number, out=print):
    ok = True

    def check(passed, line):
        nonlocal ok
        ok &= bool(passed)
        out(f"  {'OK  ' if passed else 'FAIL'} {line}")

    seen = db.execute("select gh_created_at, content_sha256, first_seen_at from prereg.issues_seen"
                      " where issue_number = %s", [number]).fetchone()
    if seen is None:
        out(f"issue {number}: the ledger never saw it")
        return False
    created, sha, first_seen = seen
    out(f"1. first sight of issue {number}: created {created:%Y-%m-%d %H:%M} UTC, seen {first_seen:%Y-%m-%d %H:%M:%S}"
        f" UTC, content sha256 {sha[:12]}...")
    it = get(f"https://api.github.com/repos/supabase/supabase/issues/{number}")
    same = content_sha256(it["title"], it["body"]) == sha
    out("2. the text on GitHub now:")
    check(same, "it has the content hash of first sight" if same else "it changed since first sight: stop here")
    if not same:
        return False

    guesses = db.execute(f"select {', '.join(FIELDS)} from prereg.predictions where issue_number = %s order by id",
                         [number]).fetchall()
    guesses = [dict(zip(FIELDS, g)) for g in guesses]
    out("3. the baseline:")
    base = [g for g in guesses if g["champion_id"] == rules_v0.CHAMPION_ID]
    area, needs_details = rules_v0.guess(it["title"], it["body"])
    check(base and (base[0]["area"], base[0]["needs_details"]) == (area, needs_details),
          f"rules_v0 run again gives {area}, needs_details {str(needs_details).lower()}, as saved")

    out("4. the champion:")
    mine = [g for g in guesses if g["champion_id"] != rules_v0.CHAMPION_ID]
    steps = db.execute("select champion_id, model, status, request_id, input_tokens, output_tokens, cost_usd,"
                       " lock_sha256, created_at from prereg.steps where issue_number = %s and job = 'tick'"
                       " order by id", [number]).fetchall()
    attempts = db.execute("select r.id, r.read_ct, r.run_id, r.created_at, (select string_agg(e.kind, ',') from"
                          " prereg.run_events e where e.data->>'attempt_id' = r.id::text) from prereg.runs r"
                          " where r.issue_number = %s order by r.id", [number]).fetchall()
    for attempt_id, read_ct, run_id, at, events in attempts:
        out(f"     attempt {attempt_id}: read {read_ct}, {at:%H:%M:%S} UTC, Actions run {run_id}, events {events or 'none'}")
    for champion_id, model, status, request_id, tin, tout, cost, lock, at in steps:
        commit, setup = lock_at(lock)
        check(setup is not None and setup["id"] == champion_id and setup["model"] == model,
              f"step {status} at {at:%H:%M:%S} UTC: {champion_id} ({model}, request {request_id}, {tin} in and"
              f" {tout} out tokens, ${cost}); models.lock {lock[:12]}... is commit {commit[:7] if commit else 'none'}")
    if not mine:
        out("     no champion guess: see the steps above")
        return ok
    g = mine[0]
    truncated = content_sha256((it["title"] or "")[:champion.MAX_TITLE], (it["body"] or "")[:champion.MAX_BODY])
    check(g["input_sha256"] == truncated, f"guess {g['id']}: {g['area']}, needs_details {str(g['needs_details']).lower()},"
          f" from the exact text the model saw (trial {g['trial']})")

    out("5. the anchor:")
    anchors = db.execute("select id, text, chain_hash, upto_prediction_id, comment_id, comment_created_at"
                         " from prereg.anchors order by id").fetchall()
    prev, low = GENESIS, 0
    for aid, text, head, upto, comment_id, comment_at in anchors:
        if upto is not None and low < g["id"] <= upto:
            rows = db.execute(f"select {', '.join(FIELDS)} from prereg.predictions where id > %s and id <= %s"
                              " order by id", [low, upto]).fetchall()
            check(anchor_text([dict(zip(FIELDS, r)) for r in rows]) == text,
                  f"anchor {aid} covers guesses {low + 1} to {upto}, and its text recomputes from the ledger")
            check(chain(prev, text) == head, f"its chain {head[:12]}... links to the anchor before it")
            since = (comment_at - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            posted = [c for c in get(f"https://api.github.com/repos/{REPO}/issues/1/comments?since={since}&per_page=100")
                      if c["id"] == comment_id]
            check(posted and posted[0]["body"] == f"{text} chain={head}",
                  f"the Notary log comment {comment_id} says exactly this, at {comment_at:%Y-%m-%d %H:%M:%S} UTC")
            label = db.execute("select min(labeled_at) from prereg.outcomes where issue_number = %s and action = 'add'"
                               " and actor = 'User' and not by_author", [number]).fetchone()[0]
            out("     the first counting human label: " + ("none yet" if label is None else
                ("after the anchor" if label > comment_at else "BEFORE the anchor, so the guess does not count")))
            return ok
        if upto is not None:
            low = upto
        prev = head
    check(False, "no anchor covers this guess yet")
    return ok


def main():
    import psycopg
    with psycopg.connect(os.environ["OBSERVER_DB_URL"], autocommit=True) as db:  # observer: reads only
        db.execute("set timezone = 'UTC'")
        sys.exit(0 if reconstruct(db, int(sys.argv[1])) else 1)


if __name__ == "__main__":
    main()
