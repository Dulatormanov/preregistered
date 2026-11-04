"""The live probes: what each token can and cannot do on the sandbox's probe issue, with GitHub's request ids.

  python probes/probe.py read    PREREG_READ_TOKEN tries to add a label: it must be DENIED
  python probes/probe.py write   PREREG_SANDBOX_WRITE adds the label and removes it: both must LAND
Each printed line is one row of the probe table in CREDENTIALS.md. The exit code is 1 if any result differs.
"""
import json
import os
import sys
import urllib.error
import urllib.request

SANDBOX, PROBE_ISSUE, LABEL = "Dulatormanov/prereg-sandbox", 1, "probe-label"


def call(token, method, path, body=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{SANDBOX}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "preregistered"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("x-github-request-id")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("x-github-request-id")


def row(token_name, action, status, request_id, want):
    got = "LANDED" if 200 <= status < 300 else "DENIED"
    print(f"| {token_name} | {action} | {got} (want {want}) | {status} | {request_id} |")
    return got == want


def main():
    add, remove = f"/issues/{PROBE_ISSUE}/labels", f"/issues/{PROBE_ISSUE}/labels/{LABEL}"
    if sys.argv[1] == "read":
        ok = row("prereg-read", f"add the label {LABEL} to the probe issue",
                 *call(os.environ["PREREG_READ_TOKEN"], "POST", add, {"labels": [LABEL]}), "DENIED")
    else:
        token = os.environ["PREREG_SANDBOX_WRITE"]
        ok = row("prereg-sandbox-write", f"add the label {LABEL} to the probe issue",
                 *call(token, "POST", add, {"labels": [LABEL]}), "LANDED")
        ok &= row("prereg-sandbox-write", f"remove the label {LABEL} again", *call(token, "DELETE", remove), "LANDED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
