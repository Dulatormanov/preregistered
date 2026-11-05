"""The only payload the gateway accepts: add one label to one issue of the sandbox repo, and nothing else.
No assignee, milestone, state, title, body, issue type or issue field can be in it (Check 15).
The bytes are canonical JSON (sorted keys, no spaces), so the owner's approval is bound to exactly these bytes."""
import json
import re

SANDBOX = "Dulatormanov/prereg-sandbox"


def canonical(issue, label):
    return json.dumps({"issue": issue, "label": label, "repo": SANDBOX}, sort_keys=True, separators=(",", ":"))


def parse(payload):
    """(issue, label) if payload is exactly a canonical payload; otherwise ValueError, with the reason."""
    try:
        d = json.loads(payload)
    except (TypeError, ValueError):
        raise ValueError("not JSON")
    if not isinstance(d, dict) or set(d) != {"issue", "label", "repo"}:
        raise ValueError("it may hold only issue, label and repo")
    if d["repo"] != SANDBOX:
        raise ValueError("not the sandbox repo")
    if type(d["issue"]) is not int or d["issue"] < 1:
        raise ValueError("not an issue number")
    if not isinstance(d["label"], str) or not re.fullmatch(r"[a-z][a-z-]{0,39}", d["label"]):
        raise ValueError("not one label name")
    if canonical(d["issue"], d["label"]) != payload:
        raise ValueError("not in canonical form")
    return d["issue"], d["label"]
