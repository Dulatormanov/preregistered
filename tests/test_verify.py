"""The public verifier (notary/verify.py) on a made-up log: an honest copy holds, an id the database skipped is not a
gap, and every kind of tampering is caught: an edited, deleted, repeated or added guess, an edited comment, a missing
anchor, an anchor by someone other than the bot, and a changed file. Run: python tests/test_verify.py"""
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notary.canonical import GENESIS, anchor_text, chain, file_text, row_text  # noqa: E402
from notary.verify import verify  # noqa: E402

FILE = b"Pre-registration, made up for this test\n"
SOON, LATER = datetime(2026, 11, 6, tzinfo=timezone.utc), datetime(2026, 11, 25, tzinfo=timezone.utc)  # 1 and 20 days


def guess(i, area):
    return {"id": i, "issue_number": 9000 + i, "champion_id": "haiku55-p2", "trial": 1, "area": area,
            "needs_details": False, "input_sha256": "h" * 64, "created_at": datetime(2026, 11, 5, 0, i, tzinfo=timezone.utc)}


def honest(ids=(1, 2, 3)):
    guesses = [guess(i, area) for i, area in zip(ids, ("auth", "frontend", "other"))]
    texts = [anchor_text(guesses[:2]), file_text("PREREGISTRATION.md", hashlib.sha256(FILE).hexdigest(), "c" * 40),
             anchor_text(guesses[2:])]
    anchors, comments, prev = [], [], GENESIS
    for i, text in enumerate(texts, 1):
        head = chain(prev, text)
        anchors.append({"id": i, "text": text, "chain_hash": head, "comment_id": 100 + i})
        comments.append({"databaseId": 100 + i, "body": f"{text} chain={head}", "lastEditedAt": None,
                         "createdAt": "2026-11-05T01:00:00Z",
                         "author": {"__typename": "Bot", "login": "github-actions"}})
        prev = head
    return [row_text(g) for g in guesses], anchors, comments


def problems(lines, anchors, comments, now=SOON):
    return verify(lines, anchors, comments, git_show=lambda commit, path: FILE, now=now)[0]


def main():
    lines, anchors, comments = honest()
    assert problems(lines, anchors, comments) == []
    assert problems(lines, anchors, comments, now=LATER) == []
    assert problems(lines[:2], anchors, comments) == []  # guess 3 not revealed yet: waiting, not a failure
    assert problems(lines[:2], anchors, comments, now=LATER)  # still missing 20 days later: deleted, or hidden
    gap = honest(ids=(1, 2, 4))  # the database skipped id 3 (a rolled-back insert): anchor 3 covers only guess 4
    assert problems(*gap[:2], gap[2], now=LATER) == []
    edited = copy.deepcopy(lines)
    edited[0] = edited[0].replace('"auth"', '"documentation"')
    assert problems([edited[0], lines[2]], anchors, comments, now=LATER)  # guess 2 deleted, guess 1 edited
    assert problems(lines + [lines[2]], anchors, comments)  # a guess revealed twice
    for extra in (guess(0, "auth"), guess(4, "other")):  # before the first anchor, and after the last
        assert problems(lines + [row_text(extra)], anchors, comments) == ["1 revealed guesses lie outside every rows anchor"]
    edited = copy.deepcopy(lines)
    edited[0] = edited[0].replace('"auth"', '"documentation"')
    assert problems(edited, anchors, comments)  # a guess changed after it was anchored
    c = copy.deepcopy(comments)
    c[1]["lastEditedAt"] = "2026-11-06T00:00:00Z"
    assert problems(lines, anchors, c)  # an anchor comment was edited
    assert problems(lines, anchors, comments[:1] + comments[2:])  # an anchor is missing
    c = copy.deepcopy(comments)
    c[0]["author"] = {"__typename": "User", "login": "someone"}
    assert problems(lines, anchors, c)  # a look-alike comment by a person is not an anchor
    a = copy.deepcopy(anchors)
    a[1]["text"] = a[1]["text"].replace("c" * 40, "d" * 40)
    assert problems(lines, a, comments)  # the published list disagrees with the log
    assert verify(lines, anchors, comments, git_show=lambda commit, path: b"another file")[0]  # the file changed
    print("ok: an honest copy holds, with or without an id gap, and an edited, deleted, repeated or added guess, an"
          " edited or missing anchor, a fake author and a changed file are each caught")


if __name__ == "__main__":
    main()
