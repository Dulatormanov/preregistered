"""The one sealed run (adopt/sealed.py) on the test database, with GitHub and Claude faked: it waits for the date,
leaves out changed issues, saves each guess once, refuses a second run, and writes counts only.

  PREREG_TEST_ADMIN_URL=... python tests/test_sealed.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import role_url  # noqa: E402
from adopt import sealed  # noqa: E402
from test_champion import reply  # noqa: E402


class FakeClaude:
    def __init__(self, **kw):
        self.messages = self

    def create(self, **kw):
        return reply('{"area": "frontend", "needs_details": false}')


def fake_read(numbers, token):  # every issue labelled studio (frontend) by a human on day 1; two have changed
    rows = {}
    for n in numbers:
        event = {"label": "studio", "action": "add", "after_s": 86400, "actor": "User", "by_author": False}
        rows[n] = {"number": n, "content_sha256": SEALED[n] if n not in CHANGED else "edited", "title": "t",
                   "body": "b", "label_events": [event]}
    return rows


def main():
    global SEALED, CHANGED
    import csv
    with open(ROOT / "golden/v1/sealed_list.csv") as f:
        SEALED = {int(r["issue_number"]): r["content_sha256"] for r in csv.DictReader(f)}
    CHANGED = set(sorted(SEALED)[:2])
    os.environ.update(ADOPTER_DB_URL=role_url("adopter"), PREREG_READ_TOKEN="fake", ANTHROPIC_API_KEY="fake")
    sealed.read, anthropic.Anthropic = fake_read, FakeClaude
    sealed.OUT = Path(tempfile.mkdtemp()) / "sealed.json"

    assert sealed.main(now=datetime(2026, 11, 15, 23, 59, tzinfo=timezone.utc)) is False  # labels not final yet
    assert not sealed.OUT.exists()
    assert sealed.main(now=datetime(2026, 11, 16, tzinfo=timezone.utc)) is True
    result = json.loads(sealed.OUT.read_text())
    assert (result["issues"], result["left_out"], result["answered"], result["agreement"]) == (151, 2, 149, 1.0)
    assert result["areas"]["frontend"]["promoted"] and result["promoted"] == ["frontend"]
    assert not any(str(n) in sealed.OUT.read_text() for n in SEALED)  # no issue number in the results
    assert sealed.main(now=datetime(2026, 11, 17, tzinfo=timezone.utc)) is False  # never runs again
    with psycopg.connect(role_url("adopter"), autocommit=True) as a:  # the run-once rule is the database's own
        try:
            a.execute("select prereg.record_sealed_guess(%s, 'x', 'ok', 'auth', false, 'h')", [max(SEALED)])
            raise AssertionError("a second guess for a sealed issue was saved")
        except psycopg.errors.UniqueViolation:
            pass
    print("ok: the sealed run waits for 2026-11-16, leaves out changed issues, runs once, and writes counts only")


if __name__ == "__main__":
    main()
