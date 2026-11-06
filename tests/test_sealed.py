"""The one sealed run (adopt/sealed.py) on the test database, with GitHub and Claude faked: it waits for the date,
leaves out changed issues, saves each guess once, never saves an API error, finishes the next day after an outage,
refuses a second run, and writes counts only. A real model check waits for the whole sealed run.

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
from agents import champion  # noqa: E402
from test_champion import reply  # noqa: E402


CALLS, FAIL = [0], [0]  # calls so far; while CALLS is under FAIL, every call fails (an outage)


class FakeClaude:
    def __init__(self, **kw):
        self.messages = self

    def create(self, **kw):
        CALLS[0] += 1
        if CALLS[0] <= FAIL[0]:
            e = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
            e.__dict__.update(status_code=529, request_id="req_down")
            raise e
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

    assert sealed.main(now=datetime(2026, 11, 7, 23, 59, tzinfo=timezone.utc)) is False  # labels not final yet
    assert not sealed.OUT.exists()
    real = champion.load()  # the test runs on any models.lock, the rollback drill's included
    champion.load = lambda: {**real, "c": {**real["c"], "id": "haiku55-p2-drill"}}
    try:
        sealed.main(now=datetime(2026, 11, 8, tzinfo=timezone.utc))
        raise AssertionError("the sealed run ran on a champion that PREREGISTRATION.md does not name")
    except SystemExit:
        pass
    champion.load = lambda: {**real, "c": {**real["c"], "id": sealed.CHAMPION}}

    sealed.WAITS = (0, 0)  # the retries, without the real waits
    FAIL[0] = 30  # an outage: the 10 issues after the 2 changed ones get 3 failed calls each
    try:
        sealed.main(now=datetime(2026, 11, 8, tzinfo=timezone.utc))
        raise AssertionError("a sealed run with API errors finished")
    except SystemExit as e:
        assert "10 issues got only API errors" in str(e), e
    assert not sealed.OUT.exists()
    with psycopg.connect(role_url("adopter"), autocommit=True) as a:
        statuses = [s for _, s, _ in a.execute("select * from prereg.sealed_rows()").fetchall()]
    assert len(statuses) == 141 and statuses.count("left_out") == 2 and "error" not in statuses, statuses
    from adopt import check  # a real check waits for the whole sealed run, and spends nothing first
    sys.argv, before = ["adopt.check", "claude-haiku-5-5"], CALLS[0]
    try:
        check.main()
        raise AssertionError("a real model check ran before the sealed run was complete")
    except SystemExit as e:
        assert "not complete" in str(e) and CALLS[0] == before, (e, CALLS[0], before)
    assert sealed.main(now=datetime(2026, 11, 17, tzinfo=timezone.utc)) is True  # the next day guesses the 10
    result = json.loads(sealed.OUT.read_text())
    assert (result["issues"], result["left_out"], result["answered"], result["agreement"]) == (151, 2, 149, 1.0)
    assert result["areas"]["frontend"]["promoted"] and result["promoted"] == ["frontend"]
    assert not any(str(n) in sealed.OUT.read_text() for n in SEALED)  # no issue number in the results
    assert sealed.main(now=datetime(2026, 11, 18, tzinfo=timezone.utc)) is False  # never runs again
    with psycopg.connect(role_url("adopter"), autocommit=True) as a:  # the run-once rule is the database's own
        try:
            a.execute("select prereg.record_sealed_guess(%s, 'x', 'ok', 'auth', false, 'h')", [max(SEALED)])
            raise AssertionError("a second guess for a sealed issue was saved")
        except psycopg.errors.UniqueViolation:
            pass
        try:  # and an API error is never an issue's one guess
            a.execute("select prereg.record_sealed_guess(1, 'x', 'error', null, null, 'h')")
            raise AssertionError("an API error was saved as a sealed guess")
        except psycopg.errors.CheckViolation:
            pass
    print("ok: the sealed run waits for 2026-11-08, refuses another champion, leaves out changed issues, saves no API"
          " error, finishes after an outage, runs once, and writes counts only")


if __name__ == "__main__":
    main()
