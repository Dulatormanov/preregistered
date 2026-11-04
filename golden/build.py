"""Build the golden set: issues created 2026-05-01 to 2026-10-31, with their label events.

  GH_TOKEN=... python golden/build.py
It keeps issue numbers, content hashes, close reasons and label events with the actor's type and whether
the actor was the issue's author. It never keeps issue text or anyone's login.
- golden/private/issues.jsonl: everything, label events included. Git ignores it: label times would show how
  fast the maintainers work, which this project does not publish.
- golden/v1/sealed_list.csv and golden/v1/SEALED.sha256: the sealed set (created 2026-09-20 to 2026-10-31),
  numbers and content hashes only, no labels. Commit both, then anchor SEALED.sha256 before any tuning.
"""
import hashlib
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from notary.canonical import content_sha256  # noqa: E402

MONTHS = [(date(2026, m, 1), date(2026, m + 1, 1) - timedelta(days=1)) for m in range(5, 11)]  # May-Oct
SEALED_FROM, SEALED_TO = date(2026, 9, 20), date(2026, 10, 31)
QUERY = """query($q: String!, $cursor: String) {
  rateLimit { remaining }
  search(type: ISSUE, query: $q, first: 50, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on Issue {
      number createdAt closedAt stateReason title body author { login }
      timelineItems(first: 100, itemTypes: [LABELED_EVENT, UNLABELED_EVENT]) {
        totalCount
        nodes {
          __typename
          ... on LabeledEvent { createdAt label { name } actor { __typename login } }
          ... on UnlabeledEvent { createdAt label { name } actor { __typename login } }
        }
      }
    } }
  }
}"""


def graphql(variables):
    req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps(
        {"query": QUERY, "variables": variables}).encode(), headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}", "User-Agent": "preregistered"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    if out.get("errors"):
        raise SystemExit(f"GraphQL error: {out['errors'][0].get('message')}")
    return out["data"]


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def issue_row(it):
    created, author = utc(it["createdAt"]), (it["author"] or {}).get("login")
    events = []
    for e in it["timelineItems"]["nodes"]:
        if not e:
            continue
        actor = e.get("actor") or {}
        events.append({"label": e["label"]["name"], "action": "add" if e["__typename"] == "LabeledEvent" else "remove",
                       "after_s": int((utc(e["createdAt"]) - created).total_seconds()),
                       "actor": actor.get("__typename", "Ghost"),
                       "by_author": bool(author) and actor.get("login") == author})
    return {"number": it["number"], "created_at": it["createdAt"], "content_sha256": content_sha256(it["title"], it["body"]),
            "closed_at": it["closedAt"], "close_reason": it["stateReason"], "label_events": events,
            "events_truncated": it["timelineItems"]["totalCount"] > 100}


def main():
    rows = []
    for first, last in MONTHS:
        q, cursor, month = f"repo:supabase/supabase is:issue created:{first}..{last}", None, []
        while True:
            d = graphql({"q": q, "cursor": cursor})
            month += [issue_row(n) for n in d["search"]["nodes"] if n]
            if not d["search"]["pageInfo"]["hasNextPage"]:
                break
            cursor = d["search"]["pageInfo"]["endCursor"]
        assert len(month) == d["search"]["issueCount"] < 1000, (first, len(month), d["search"]["issueCount"])
        print(f"{first:%Y-%m}: {len(month)} issues (rate limit left: {d['rateLimit']['remaining']})")
        rows += month
    private = ROOT / "golden/private"
    private.mkdir(parents=True, exist_ok=True)
    (private / "issues.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in sorted(rows, key=lambda r: r["number"])))
    sealed = sorted((r for r in rows if SEALED_FROM <= date.fromisoformat(r["created_at"][:10]) <= SEALED_TO),
                    key=lambda r: r["number"])
    listing = "issue_number,content_sha256\n" + "".join(f"{r['number']},{r['content_sha256']}\n" for r in sealed)
    (ROOT / "golden/v1").mkdir(parents=True, exist_ok=True)
    (ROOT / "golden/v1/sealed_list.csv").write_text(listing)
    digest = hashlib.sha256(listing.encode()).hexdigest()
    (ROOT / "golden/v1/SEALED.sha256").write_text(
        f"{digest}  sealed_list.csv\n# {len(sealed)} issues created {SEALED_FROM} to {SEALED_TO}; numbers and content"
        f" hashes only, no labels. Fixed before any tuning.\n")
    dev = sum(date.fromisoformat(r["created_at"][:10]) < SEALED_FROM for r in rows)
    print(f"total {len(rows)}: dev {dev}, sealed {len(sealed)}; sealed sha256 {digest}")


if __name__ == "__main__":
    main()
