"""The triage scorer: the answer's area must equal the issue's ground-truth area."""
import json


def score(text, case):
    """(passed, code) for one answer: ok, wrong_area, invalid or no_answer."""
    if text is None:
        return False, "no_answer"
    try:
        area = json.loads(text)["area"]
    except (ValueError, TypeError, KeyError):
        return False, "invalid"
    return (True, "ok") if area == case["area"] else (False, "wrong_area")
