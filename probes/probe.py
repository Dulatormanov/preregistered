"""The live probes: what each token can and cannot do on the sandbox's probe issue, with GitHub's request ids.

  python probes/probe.py read    PREREG_READ_TOKEN tries to add a label: it must be DENIED. The same job also
                                 checks that PREREG_SANDBOX_WRITE does not reach it: a job outside the environment
                                 must get an empty value, or the token is a repository secret that any run can read.
  python probes/probe.py write   PREREG_SANDBOX_WRITE adds the label and removes it: both must LAND
Each printed line is one row of the probe table in CREDENTIALS.md. The exit code is 1 if any result differs.
DENIED means GitHub's own permission refusal (403, "Resource not accessible ..."). Any other failure, such as a
dead token (401), a rate limit or a GitHub error, is ERROR, so it can never pass for a denial.
"""
import json
import os
import sys
import urllib.error
import urllib.request

SANDBOX, PROBE_ISSUE, LABEL = "Dulatormanov/prereg-sandbox", 1, "probe-label"


def call(token, method, path, body=None):
    """(HTTP status, GitHub's request id, GitHub's error message or "")."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{SANDBOX}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "preregistered"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("x-github-request-id"), ""
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read() or b"{}").get("message", "")
        except ValueError:
            message = ""
        return e.code, e.headers.get("x-github-request-id"), message
    except urllib.error.URLError as e:  # no answer at all
        return 0, None, type(e.reason).__name__


def result(status, message):
    if 200 <= status < 300:
        return "LANDED"
    if status == 403 and message.startswith("Resource not accessible"):
        return "DENIED"
    return "ERROR"


def row(token_name, action, status, request_id, message, want):
    got = result(status, message)
    print(f"| {token_name} | {action} | {got} (want {want}) | {status} | {request_id} |")
    return got == want


def main():
    add, remove = f"/issues/{PROBE_ISSUE}/labels", f"/issues/{PROBE_ISSUE}/labels/{LABEL}"
    if sys.argv[1] == "read":
        ok = row("prereg-read", f"add the label {LABEL} to the probe issue",
                 *call(os.environ["PREREG_READ_TOKEN"], "POST", add, {"labels": [LABEL]}), "DENIED")
        leaked = bool(os.environ.get("PREREG_SANDBOX_WRITE"))  # the value itself is never printed
        print(f"| prereg-sandbox-write | reach a job outside the environment | {'PRESENT' if leaked else 'ABSENT'}"
              " (want ABSENT) | - | - |")
        ok &= not leaked
    else:
        token = os.environ["PREREG_SANDBOX_WRITE"]
        ok = row("prereg-sandbox-write", f"add the label {LABEL} to the probe issue",
                 *call(token, "POST", add, {"labels": [LABEL]}), "LANDED")
        ok &= row("prereg-sandbox-write", f"remove the label {LABEL} again", *call(token, "DELETE", remove), "LANDED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
