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
    assert score(guesses, ROWS, rules("pre-registered rule")) == (3, 3, 3)  # issue 4 is not scorable
    assert score(guesses, ROWS, rules("labels within 7 days")) == (2, 2, 2)  # issue 2's label comes too late
    assert score(guesses, ROWS, rules("bot and agent labels count")) == (3, 3, 2)  # issue 3 becomes auth: wrong
    assert score(guesses, ROWS, rules("the author's template labels count")) == (4, 4, 4)
    # The time rule: a guess anchored after the first counting label does not count.
    key = json.dumps(rules("pre-registered rule"), sort_keys=True)
    late = [dict(ROWS[0], first_label_s={key: 2 * DAY})]
    assert score({1: ("auth", 3 * DAY)}, late, rules("pre-registered rule")) == (1, 0, 0)
    assert score({1: ("auth", DAY)}, late, rules("pre-registered rule")) == (1, 1, 1)
    assert cell(4, 2, 1, coverage=True) == "50.0% of 2, coverage 50%" and cell(0, 0, 0) == "none scorable yet"
    print("ok: each ground-truth switch changes what is scorable as it should, and the time rule holds")


if __name__ == "__main__":
    main()
