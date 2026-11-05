"""The live probes: what each token can and cannot do on the sandbox's probe issue, with GitHub's request ids.

  python probes/probe.py read    PREREG_READ_TOKEN tries to add a label: it must be DENIED. The same job also
                                 checks that PREREG_SANDBOX_WRITE does not reach it: a job outside the environment
                                 must get an empty value, or the token is a repository secret that any run can read.
  python probes/probe.py write   PREREG_SANDBOX_WRITE adds the label and removes it: both must LAND
  python probes/probe.py gateway in every promotion run: the gateway refuses to assign, close or set a milestone,
                                 and the probe issue reads back unchanged; the token itself, outside the gateway, can
                                 assign (undone at once) and can open the side door (undone); the gateway refuses it
Each printed line is one row of the probe table in CREDENTIALS.md. The exit code is 1 if any result differs.
DENIED means GitHub's own permission refusal (403, "Resource not accessible ..."). Any other failure, such as a
dead token (401), a rate limit or a GitHub error, is ERROR, so it can never pass for a denial.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the gateway's payload rules, for gateway mode
SANDBOX, PROBE_ISSUE, LABEL = "Dulatormanov/prereg-sandbox", 1, "probe-label"
SIDE_DOOR_ISSUE, SIDE_DOOR, OWNER = 25, "probe-side-door", "Dulatormanov"


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


def state(token, issue):
    """What a write could change on an issue: its state, assignees, milestone and labels."""
    req = urllib.request.Request(f"https://api.github.com/repos/{SANDBOX}/issues/{issue}", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "preregistered"})
    with urllib.request.urlopen(req, timeout=30) as r:
        it = json.load(r)
    return (it["state"], sorted(a["login"] for a in it["assignees"]), (it.get("milestone") or {}).get("number"),
            sorted(lab["name"] for lab in it["labels"]))


def gateway_probes(token, wait=lambda: time.sleep(10)):
    """The promotion run's live probes (Build day 6): what the gateway refuses, and what the token itself can do."""
    from gateway import payload
    from probes.closure import side_door_labels
    ok, before = True, state(token, PROBE_ISSUE)
    for what, text in (("assign the owner", {"assignees": [OWNER]}), ("close the issue", {"state": "closed"}),
                       ("set a milestone", {"milestone": 1})):
        try:
            payload.parse(json.dumps({"issue": PROBE_ISSUE, "label": LABEL, "repo": SANDBOX, **text}, sort_keys=True,
                                     separators=(",", ":")))
            got = "LANDED"
        except ValueError:
            got = "REFUSED"
        print(f"| gateway | {what} on the probe issue | {got} (want REFUSED) | - | - |")
        ok &= got == "REFUSED"
    unchanged = state(token, PROBE_ISSUE) == before
    print(f"| gateway | read the probe issue back | {'unchanged' if unchanged else 'CHANGED'} (want unchanged) | - | - |")
    ok &= unchanged
    # The same token used directly can do what the gateway refuses. Then it is undone at once.
    ok &= row("prereg-sandbox-write", "assign the owner directly, outside the gateway",
              *call(token, "POST", f"/issues/{PROBE_ISSUE}/assignees", {"assignees": [OWNER]}), "LANDED")
    ok &= row("prereg-sandbox-write", "remove that assignee again",
              *call(token, "DELETE", f"/issues/{PROBE_ISSUE}/assignees", {"assignees": [OWNER]}), "LANDED")
    # The side door: one label, added directly, makes a sandbox workflow close the issue.
    ok &= row("prereg-sandbox-write", f"add {SIDE_DOOR} directly to the side-door target",
              *call(token, "POST", f"/issues/{SIDE_DOOR_ISSUE}/labels", {"labels": [SIDE_DOOR]}), "LANDED")
    for _ in range(18):  # the demo workflow needs a minute or so to start
        wait()
        if state(token, SIDE_DOOR_ISSUE)[0] == "closed":
            break
    closed = state(token, SIDE_DOOR_ISSUE)[0] == "closed"
    print(f"| side door | side_door_demo.yml closed the issue | {'LANDED' if closed else 'ERROR'} (want LANDED) | - | - |")
    ok &= closed
    call(token, "PATCH", f"/issues/{SIDE_DOOR_ISSUE}", {"state": "open"})  # undo, directly
    call(token, "DELETE", f"/issues/{SIDE_DOOR_ISSUE}/labels/{SIDE_DOOR}")
    refused = SIDE_DOOR in side_door_labels(token)
    print(f"| gateway | add {SIDE_DOOR} through the gateway | {'REFUSED' if refused else 'LANDED'} (want REFUSED) | - | - |")
    return ok & refused


def main():
    add, remove = f"/issues/{PROBE_ISSUE}/labels", f"/issues/{PROBE_ISSUE}/labels/{LABEL}"
    if sys.argv[1] == "gateway":
        sys.exit(0 if gateway_probes(os.environ["PREREG_SANDBOX_WRITE"]) else 1)
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
