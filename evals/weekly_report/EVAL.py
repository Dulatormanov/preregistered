"""The report scorer: the summary must break none of the four failure modes (agents/report_checks.py)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.report_checks import check  # noqa: E402


def score(text, case):
    """(passed, code): ok, no_answer, or the first failure mode the summary breaks."""
    if not text:
        return False, "no_answer"
    broken = check(text, json.loads(case["body"]))  # the case's numbers, as the agent saw them
    return (False, broken[0]) if broken else (True, "ok")
