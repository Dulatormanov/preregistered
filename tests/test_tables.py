"""The sensitivity table's scoring (tools/tables.py), on made-up label histories. Run: python tests/test_tables.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from golden.truth import RULES  # noqa: E402
from tools.tables import VARIANTS, cell, score  # noqa: E402

DAY = 86400


def event(label, after_s, actor="User", by_author=False):
    return {"label": label, "action": "add", "after_s": after_s, "actor": actor, "by_author": by_author}


ROWS = [
    {"number": 1, "label_events": [event("auth", 2 * DAY)]},  # a human, on day 2
    {"number": 2, "label_events": [event("studio", 10 * DAY)]},  # a human, on day 10
    {"number": 3, "label_events": [event("auth", 60, actor="Bot"), event("studio", DAY)]},  # a bot first
    {"number": 4, "label_events": [event("auth", 0, by_author=True)]},  # the author's issue form
]


def rules(name):
    return {**RULES, **dict(VARIANTS)[name]}


def main():
    guesses = {1: ("auth", 0), 2: ("frontend", 0), 3: ("frontend", 0), 4: ("auth", 0)}
    assert score(guesses, ROWS, rules("pre-registered rule")) == (2, 2, 2)  # issue 2's label (day 10) is too late
    assert score(guesses, ROWS, rules("labels within 14 days (v1's rule)")) == (3, 3, 3)  # issue 4 is not scorable
    assert score(guesses, ROWS, rules("bot and agent labels count")) == (2, 2, 1)  # issue 3 becomes auth: wrong
    assert score(guesses, ROWS, rules("the author's template labels count")) == (3, 3, 3)  # issue 4 counts
    # The time rule: a guess anchored after the first counting label does not count.
    key = json.dumps(rules("pre-registered rule"), sort_keys=True)
    late = [dict(ROWS[0], first_label_s={key: 2 * DAY})]
    assert score({1: ("auth", 3 * DAY)}, late, rules("pre-registered rule")) == (1, 0, 0)
    assert score({1: ("auth", DAY)}, late, rules("pre-registered rule")) == (1, 1, 1)
    from datetime import datetime, timezone  # the final report (tools/final_report.py), on public-style rows
    from tools import final_report
    key = json.dumps(rules("pre-registered rule"), sort_keys=True)
    window = {r["number"]: dict(r, first_label_s={key: s}) for r, s in (
        ({"number": 1, "label_events": [event("auth", 2 * DAY)]}, 2 * DAY),
        ({"number": 2, "label_events": []}, float("inf")),  # never labelled: not scorable
        ({"number": 3, "label_events": [event("studio", DAY), event("awaiting-details", DAY)]}, DAY),
        ({"number": 4, "label_events": [event("auth", 10 * DAY)]}, float("inf")))}  # too late for 7 days
    series = {"champion": {1: ("auth", 60, False), 3: ("frontend", 120, True), 4: ("auth", 60, False)},
              "baseline": {1: ("other", 60, False)}}
    text = final_report.report(window, series, 9, {"agreement": 0.8, "promoted": ["auth"]},
                               datetime(2026, 11, 21, 4, 17, tzinfo=timezone.utc))
    assert "4, of which 2 are scorable" in text, text
    assert "| champion | 2 of 2, 100.0% (34.2% to 100.0%) | 2 of 2, 100% | 2 of 2 |" in text, text
    assert "| baseline | 0 of 1, 0.0% (0.0% to 79.3%) | 1 of 2, 50% | 1 of 1 |" in text, text
    assert "agreement 80.0%; promoted areas: auth." in text and "within 7 days" in text, text
    assert final_report.FINAL == datetime(2026, 11, 21, tzinfo=timezone.utc)
    assert cell(4, 2, 1, coverage=True) == "50.0% of 2, coverage 50%" and cell(0, 0, 0) == "none scorable yet"
    print("ok: each ground-truth switch changes what is scorable as it should, and the time rule holds")


if __name__ == "__main__":
    main()
