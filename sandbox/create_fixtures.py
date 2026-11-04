"""Open the 20 prompt-injection fixtures as issues in the sandbox, once. Run: GH_TOKEN=... python sandbox/create_fixtures.py

Each issue says it is a test fixture, and that its canary is fake. An issue whose title already exists is skipped.
"""
import json
import os
import tomllib
import urllib.request
from pathlib import Path

SANDBOX = "Dulatormanov/prereg-sandbox"
CASES = tomllib.loads((Path(__file__).resolve().parent / "injection_cases.toml").read_text())["case"]
FOOTER = ("\n\n---\nTest fixture {id} for the safety suite of Dulatormanov/preregistered. It tries to steer an AI"
          " triage agent ({attack}). Its canary is fake, and must never appear in any output.")


def api(method, path, body=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{SANDBOX}{path}", method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "User-Agent": "preregistered",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    existing = {i["title"] for i in api("GET", "/issues?state=all&per_page=100")}
    made = 0
    for c in CASES:
        if c["title"] in existing:
            continue
        api("POST", "/issues", {"title": c["title"], "body": c["body"] + FOOTER.format(**c)})
        made += 1
    print(f"fixtures: {len(CASES)} in the file, {made} opened now, {len(CASES) - made} already there")


if __name__ == "__main__":
    main()
