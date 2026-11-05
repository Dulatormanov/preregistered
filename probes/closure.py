"""The side doors: labels that a sandbox workflow reacts to. Writing one of them could make GitHub do more than add a
label (side_door_demo.yml closes the issue), so the gateway refuses them all (Build day 6).

  GH_TOKEN=... python probes/closure.py   prints the labels
A workflow that runs on `labeled` and names no label in a condition reacts to every label: then the answer is "*",
and the gateway refuses everything. So does a workflow file that cannot be read.
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

SANDBOX = "Dulatormanov/prereg-sandbox"


def labels_in(text):
    """The labels one workflow file reacts to: a set of names, {"*"} for all, or the empty set."""
    if not re.search(r"\blabeled\b", text):
        return set()
    names = set(re.findall(r"""label\.name\s*==\s*['"]([^'"]+)['"]""", text))
    return names or {"*"}


def side_door_labels(token, get=None):
    def fetch(path):
        req = urllib.request.Request(f"https://api.github.com/repos/{SANDBOX}/contents/{path}",
                                     headers={"Authorization": f"Bearer {token}", "User-Agent": "preregistered"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    get = get or fetch
    try:
        files = get(".github/workflows")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()  # no workflows at all
        return {"*"}
    doors = set()
    for f in files:
        try:
            doors |= labels_in(base64.b64decode(get(f["path"])["content"]).decode())
        except Exception:
            doors.add("*")  # unreadable: refuse every label
    return doors


if __name__ == "__main__":
    print(" ".join(sorted(side_door_labels(os.environ.get("GH_TOKEN", "")))) or "none")
    sys.exit(0)
