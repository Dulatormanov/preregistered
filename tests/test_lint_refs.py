"""Checks the reference lint. Run: python3 tests/test_lint_refs.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lint_refs import check  # noqa: E402

BLOCKED = [
    "see supabase/supabase#52752",
    "https://github.com/supabase/supabase/issues/52752",
    "https://github.com/supabase/supabase/pull/1",
    "the guess for #52752 was wrong",
    "thanks @kangmingtay",
    "(#12)",
]
ALLOWED = [
    "canon=v1 kind=rows upto=7 n=3 rows=19f7a6b6b79b925c86f8e415d23ec6b0d5fd0cf70572cf4ea65d3c10d3dffd42 chain=5c3b",
    "canon=v1 kind=file file=PREREGISTRATION.md sha256=1832 commit=4567c8b",
    "Notary log: https://github.com/Dulatormanov/preregistered/issues/1",
    "write to dulat@example.com",
    "select data @> '{}'",
    "colour #ff0000 and C# code",
    "3 guesses, 0 dead letters, 1 alert (ledger id 41)",
]


def test_blocked():
    for text in BLOCKED:
        assert check(text), f"not blocked: {text!r}"


def test_allowed():
    for text in ALLOWED:
        assert not check(text), f"blocked: {text!r} -> {check(text)}"


if __name__ == "__main__":
    test_blocked()
    test_allowed()
    print("ok")
