"""The public verifier (notary/verify.py) on a made-up log: an honest copy holds, and every kind of tampering is caught:
an edited guess, an edited comment, a missing anchor, an anchor by someone other than the bot, and a changed file.
Run: python tests/test_verify.py"""
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


def guess(i, area):
    return {"id": i, "issue_number": 9000 + i, "champion_id": "haiku55-p2", "trial": 1, "area": area,
            "needs_details": False, "input_sha256": "h" * 64, "created_at": datetime(2026, 11, 5, 0, i, tzinfo=timezone.utc)}


def honest():
    guesses = [guess(1, "auth"), guess(2, "frontend"), guess(3, "other")]
    texts = [anchor_text(guesses[:2]), file_text("PREREGISTRATION.md", hashlib.sha256(FILE).hexdigest(), "c" * 40),
             anchor_text(guesses[2:])]
    anchors, comments, prev = [], [], GENESIS
    for i, text in enumerate(texts, 1):
        head = chain(prev, text)
        anchors.append({"id": i, "text": text, "chain_hash": head, "comment_id": 100 + i})
        comments.append({"databaseId": 100 + i, "body": f"{text} chain={head}", "lastEditedAt": None,
                         "author": {"__typename": "Bot", "login": "github-actions"}})
        prev = head
    return [row_text(g) for g in guesses], anchors, comments


def problems(lines, anchors, comments):
    return verify(lines, anchors, comments, git_show=lambda commit, path: FILE)[0]


def main():
    lines, anchors, comments = honest()
    assert problems(lines, anchors, comments) == []
    assert problems(lines[:2], anchors, comments) == []  # guess 3 not revealed yet: waiting, not a failure
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
    print("ok: an honest copy holds, and an edited guess, an edited or missing anchor, a fake author and a changed file"
          " are each caught")


if __name__ == "__main__":
    main()
