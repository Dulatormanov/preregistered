"""The daily outcomes job: save every label event on the issues the ledger has seen, as the collector role.

Reads COLLECTOR_DB_URL and PREREG_READ_TOKEN. Prints counts only: Actions logs are public. When a label
appears that rules/ground_truth.toml neither maps nor ignores, it writes unknown=<labels> to GITHUB_OUTPUT,
so the next job can open one alert issue. It keeps actor types only, never a login.
"""
import hashlib
import json
import os
import tomllib
import urllib.request
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
RULES = tomllib.loads((ROOT / "rules/ground_truth.toml").read_text())
KNOWN = {label for labels in RULES["areas"].values() for label in labels} | set(RULES["ignore"]["labels"])
WATCH_DAYS = 29  # the longest label window (28 days) plus one
BATCH = 40  # issues per GraphQL query
EVENT = "createdAt label { name } actor { __typename login }"


def query(numbers):
    fields = "".join(
        f" i{n}: issue(number: {int(n)}) {{ author {{ login }} timelineItems(first: 100,"
        f" itemTypes: [LABELED_EVENT, UNLABELED_EVENT]) {{ nodes {{ __typename"
        f" ... on LabeledEvent {{ id {EVENT} }} ... on UnlabeledEvent {{ id {EVENT} }} }} }} }}" for n in numbers)
    req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps(
        {"query": f'{{ repository(owner: "supabase", name: "supabase") {{{fields} }} }}'}).encode(), headers={
        "Authorization": f"Bearer {os.environ['PREREG_READ_TOKEN']}", "User-Agent": "preregistered"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    errors = sorted({e.get("type", "?") for e in data.get("errors", []) if e.get("type") != "NOT_FOUND"})
    repo = (data.get("data") or {}).get("repository")
    if errors or repo is None:  # fail loudly: an empty answer must not look like a day with no new labels
        raise SystemExit(f"GraphQL failed: error types {errors}, repository {'missing' if repo is None else 'present'}")
    return repo  # a deleted issue comes back as null, with a NOT_FOUND error


def main():
    issues = events = new = 0
    unknown = set()
    with psycopg.connect(os.environ["COLLECTOR_DB_URL"], autocommit=True, connect_timeout=20) as db:
        numbers = [n for (n,) in db.execute(
            "select issue_number from prereg.issues_seen where gh_created_at > now() - %s * interval '1 day'"
            " order by issue_number", [WATCH_DAYS]).fetchall()]
        for i in range(0, len(numbers), BATCH):
            repo = query(numbers[i:i + BATCH])  # no transaction is open during the network call
            for n in numbers[i:i + BATCH]:
                issue = repo.get(f"i{n}")
                if not issue:
                    continue
                issues += 1
                author = (issue.get("author") or {}).get("login")
                for e in issue["timelineItems"]["nodes"]:
                    actor = e.get("actor") or {}
                    events += 1
                    unknown |= {e["label"]["name"]} - KNOWN
                    saved = db.execute(
                        "select prereg.record_outcome(%s, %s, %s, %s, %s, %s, %s)",
                        [n, hashlib.sha256(e["id"].encode()).hexdigest(), e["label"]["name"],
                         "add" if e["__typename"] == "LabeledEvent" else "remove", actor.get("__typename", "Ghost"),
                         bool(author) and actor.get("login") == author, e["createdAt"]]).fetchone()[0]
                    new += bool(saved)
    print(f"outcomes: issues={issues} events={events} new={new} unknown_labels={len(unknown)}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"unknown={', '.join(sorted(unknown))}\n")


if __name__ == "__main__":
    main()
