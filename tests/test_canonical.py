"""Freezes canonical format v1 and rules_v0. Run: python3 tests/test_canonical.py

If a test here fails, the published hashes can no longer be recomputed. Add v2 instead.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents import rules_v0  # noqa: E402
from notary.canonical import GENESIS, anchor_text, chain, content_sha256, row_text  # noqa: E402

ROW = {"id": 1, "issue_number": 12345, "champion_id": "rules_v0", "trial": 1, "area": "auth",
       "needs_details": False, "input_sha256": content_sha256("Magic link login fails", "Steps: ..."),
       "created_at": datetime(2026, 11, 4, 0, 7, 30, 123456, tzinfo=timezone.utc)}
ROW2 = dict(ROW, id=2, issue_number=12346, area="frontend", needs_details=True,
            input_sha256=content_sha256("Studio button broken", None),
            created_at=datetime(2026, 11, 4, 0, 22, 41, 654321, tzinfo=timezone.utc))


def test_v1_is_frozen():
    assert ROW["input_sha256"] == "24ef368661fe9fab5c085e75c716c5041c1792f84ae426f6b509d55da6c68015"
    assert row_text(ROW) == (
        '{"area":"auth","champion_id":"rules_v0","created_at":"2026-11-04T00:07:30.123456Z","id":1,'
        '"input_sha256":"24ef368661fe9fab5c085e75c716c5041c1792f84ae426f6b509d55da6c68015",'
        '"issue_number":12345,"needs_details":false,"trial":1}')
    text = anchor_text([ROW])
    assert text == "canon=v1 kind=rows upto=1 n=1 rows=68742e48ffd39cff0ff6c94017ae2a1097e8b3f6329afb8e1c952bfdd31857f8"
    assert chain(GENESIS, text) == "d8acf4c2194c46be98d52661eb0ed60fb2e50692a41811ea2b38f0f291190f59"


def test_two_rows_and_a_second_link_are_frozen():
    text = anchor_text([ROW, ROW2])  # pins the "\n" between rows
    assert text == "canon=v1 kind=rows upto=2 n=2 rows=19f7a6b6b79b925c86f8e415d23ec6b0d5fd0cf70572cf4ea65d3c10d3dffd42"
    assert chain(GENESIS, text) == "d57f53679f3de152ad178625a6fcc272201748cb77f95221c3ea8fd5f8d95acc"
    first = chain(GENESIS, anchor_text([ROW]))
    second = anchor_text([ROW2])
    assert second == "canon=v1 kind=rows upto=2 n=1 rows=1527a8a0ad0c7c30f83dc816c41078f68c57d0763bae52afad4bf1c20e9cf515"
    assert chain(first, second) == "7d55649d93534aa1965f1fb827f940877c5ceef622bf630b1e74d67f773431ea"


def test_times_are_utc():
    almaty = ROW["created_at"].astimezone(timezone(timedelta(hours=5)))
    assert row_text(dict(ROW, created_at=almaty)) == row_text(ROW)


def test_rules_v0():
    long = "x" * 300
    assert rules_v0.guess("Magic link login fails", long) == ("auth", False)
    assert rules_v0.guess("SQL editor freezes", long) == ("frontend", False)
    assert rules_v0.guess("Typo in docs", "") == ("documentation", True)
    assert rules_v0.guess("Something odd", None) == ("other", True)
    assert rules_v0.guess("Help", "self-hosted with docker compose " + long) == ("self-hosted", False)


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
    print("ok")
