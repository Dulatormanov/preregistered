"""One tick end to end, on the test database: the real runner/poll.py, runner/worker.py and notary/anchor.py,
with a fake GitHub and a fake Claude. Run after tests/setup_test_db.py:
  PREREG_TEST_ADMIN_URL=... python tests/test_tick.py
It empties the ledger and the queues first, so it runs only on a local test database.
"""
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.chdir(ROOT)
import anthropic  # noqa: E402
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from setup_test_db import admin_url, role_url  # noqa: E402

from agents import champion  # noqa: E402
from notary import anchor  # noqa: E402
from notary.canonical import FIELDS, GENESIS, anchor_text, chain, content_sha256, file_text  # noqa: E402
from runner import poll, worker  # noqa: E402
from tools.reconstruct import reconstruct  # noqa: E402

worker.VT = 1  # a claimed message comes back after 1 second in this test
NOW = datetime.now(timezone.utc)
ISSUES, COMMENTS, DELETED, BROKEN, FAIL, DOWN = [], [], set(), set(), [False], [False]  # BROKEN: GET answers 502


class Resp(io.BytesIO):
    def __init__(self, obj, status=200):
        super().__init__(json.dumps(obj).encode())
        self.status, self.headers = status, {"github-authentication-token-expiration": "2027-02-01 19:00:00 UTC"}


def fake_urlopen(req, timeout=None):
    u = urllib.parse.urlparse(req.full_url)
    q = urllib.parse.parse_qs(u.query)
    if u.path == "/repos/supabase/supabase/issues":
        if DOWN[0]:
            raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, None)
        page, per = int(q["page"][0]), int(q["per_page"][0])
        live = sorted((i for i in ISSUES if i["number"] not in DELETED), key=lambda i: i["created_at"], reverse=True)
        return Resp(live[(page - 1) * per: page * per])
    if u.path.startswith("/repos/supabase/supabase/issues/"):
        n = int(u.path.rsplit("/", 1)[1])
        if n in BROKEN:
            raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)
        hit = [i for i in ISSUES if i["number"] == n and i["number"] not in DELETED]
        if not hit:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return Resp(hit[0])
    if u.path == "/repos/Dulatormanov/preregistered/issues/1/comments":
        if req.get_method() == "POST":
            c = {"id": 9000 + len(COMMENTS), "body": json.loads(req.data)["body"], "user": {"login": "github-actions[bot]"},
                 "created_at": (datetime.now(timezone.utc) + timedelta(seconds=len(COMMENTS))).strftime("%Y-%m-%dT%H:%M:%SZ")}
            COMMENTS.append(c)
            return Resp(c, 201)
        return Resp([c for c in COMMENTS if c["created_at"] >= q["since"][0]][:100])
    raise AssertionError(f"unexpected request {req.full_url}")


class FakeClaude:
    calls = []

    def __init__(self, **kw):
        self.messages = self

    def create(self, **kw):
        text = kw["messages"][0]["content"]
        FakeClaude.calls.append(text)
        if FAIL[0] or "BOOM" in text:
            e = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
            e.__dict__.update(status_code=529, request_id="req_err")
            raise e
        if "REFUSE" in text:
            return reply("", "refusal")
        return reply(json.dumps({"area": "auth" if "login" in text.lower() else "other", "needs_details": False}))


def reply(text, stop="end_turn"):
    r = NS(stop_reason=stop, content=[NS(type="text", text=text)],
           usage=NS(input_tokens=1500, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    r._request_id = "req_ok"
    return r


def issue(n, title, minutes_ago=0):
    ISSUES.append({"number": n, "title": title, "body": f"body of {title}", "labels": [{"name": "bug"}],
                   "created_at": (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")})


def look(sql, *args):
    with psycopg.connect(admin_url(), autocommit=True) as c:
        c.execute("set role prereg_owner")
        return c.execute(sql, args).fetchall()


def tick(fails=False):
    out = ROOT / ".tick_output"
    out.write_text("")
    os.environ["GITHUB_OUTPUT"] = str(out)
    try:
        poll.main()
        assert not fails, "the tick should have failed"
    except (SystemExit, urllib.error.HTTPError) as e:
        assert fails, f"the tick failed: {e!r}"
    finally:
        o = dict(line.split("=", 1) for line in out.read_text().split())
        out.unlink()
    return o


def reset():
    with psycopg.connect(admin_url(), autocommit=True) as c:
        c.execute("select pgmq.purge_queue('triage_events'), pgmq.purge_queue('triage_dlq')")
        c.execute("set role prereg_owner")
        c.execute("truncate prereg.outcomes, prereg.runs, prereg.steps, prereg.run_events, prereg.anchors,"
                  " prereg.predictions, prereg.issues_seen restart identity")


def main():
    reset()
    urllib.request.urlopen = fake_urlopen
    anthropic.Anthropic = FakeClaude
    os.environ.update(TRIAGE_DB_URL=role_url("triage_agent"), NOTARY_DB_URL=role_url("notary"),
                      PREREG_READ_TOKEN="fake", ANTHROPIC_API_KEY="fake", GITHUB_REPOSITORY="Dulatormanov/preregistered",
                      NOTARY_ISSUE="1", GH_TOKEN="fake", GITHUB_SHA="a" * 40, ANCHOR_FILE="")
    champion_id = champion.load()["c"]["id"]

    def guesses(n):
        return look("select champion_id, area from prereg.predictions where issue_number = %s order by id", n)

    # 1. three new issues: baseline and champion guesses, one step each, then one rows anchor
    issue(101, "Magic login link fails", 50); issue(102, "Table editor is slow", 40); issue(103, "Odd thing", 30)
    assert tick() == {"pending": "6", "anchor": "yes"}
    assert guesses(101) == [("rules_v0", "auth"), (champion_id, "auth")]
    assert look("select count(*) from prereg.steps where status = 'ok'")[0][0] == 3
    assert look("select data->>'token_expires' from prereg.run_events where kind = 'polled'") == [
        ("2027-02-01 19:00:00 UTC",)]
    anchor.main()
    assert len(COMMENTS) == 1 and COMMENTS[0]["body"].startswith("canon=v1 kind=rows upto=6 n=6 ")
    print("ok 1: 3 issues -> 3 baseline and 3 champion guesses, 3 steps, 1 rows anchor")
    with psycopg.connect(role_url("observer"), autocommit=True) as o:  # tools/reconstruct.py rebuilds one of them
        lines = []
        assert reconstruct(o, 101, out=lines.append), "\n".join(lines)
        assert sum(line.startswith("  OK") for line in lines) == 7 and "Magic" not in "".join(lines)  # no issue text
    print("ok 1b: reconstruct.py rebuilds issue 101 from the ledger, git, GitHub and the Notary log")

    # 2. a provider error: the step is saved, the run stops claiming, the job fails, the message comes back
    FAIL[0] = True
    issue(104, "Login button broken", 20)
    assert tick(fails=True) == {"pending": "1", "anchor": "yes"}  # outputs come before the failure
    assert look("select status from prereg.steps where issue_number = 104") == [("error",)]
    print("ok 2: an error saves a failed step, stops the run and fails the job")

    # 3. the breaker: while the provider still fails, the probe fails and nothing is claimed; then it recovers
    calls = len(FakeClaude.calls)
    tick(fails=True)
    assert len(FakeClaude.calls) == calls + 1 and champion.PROBE[0] in FakeClaude.calls[-1]  # the probe only
    assert look("select read_ct from pgmq.q_triage_events")[0][0] == 0  # sent back fresh; no read during the outage
    FAIL[0] = False
    time.sleep(1.1)  # the failed message is hidden for worker.VT = 1 second
    tick()
    assert guesses(104)[-1] == (champion_id, "auth")
    print("ok 3: the breaker probes, claims nothing while the probe fails, and resumes after it")

    # 4. a refusal is final: the message completes with no guess, and is never called again
    issue(105, "REFUSE this", 10)
    tick()
    calls = len(FakeClaude.calls)
    tick()
    assert guesses(105) == [("rules_v0", "other")] and not any("REFUSE" in c for c in FakeClaude.calls[calls:])
    print("ok 4: a refused issue completes with no guess")

    # 5. an issue edited before its retry completes as gone; 6. a deleted one too
    FAIL[0] = True
    issue(106, "Studio crash", 5); issue(107, "Auth email bounce", 5)
    tick(fails=True)
    FAIL[0] = False
    next(i for i in ISSUES if i["number"] == 106)["title"] = "[Auth] Studio crash"  # a maintainer's retitle
    DELETED.add(107)
    tick()
    tick()
    assert look("select error from prereg.steps where issue_number in (106, 107) and status = 'skipped'"
                " order by issue_number") == [("edited after first sight",), ("HTTPError 404",)]
    assert guesses(106) == [("rules_v0", "frontend")] and guesses(107) == [("rules_v0", "auth")]
    print("ok 5-6: an issue edited or deleted before its retry gets no champion guess")

    # 7. the daily cap: at $3 the worker makes no call; the baseline still guesses
    with psycopg.connect(admin_url(), autocommit=True) as c:
        c.execute("set role prereg_owner; insert into prereg.steps (job, champion_id, model, status, cost_usd,"
                  " lock_sha256) values ('tick', 'x', 'x', 'ok', 3, 'x')")
    issue(108, "After the cap", 0)
    calls = len(FakeClaude.calls)
    tick()
    assert len(FakeClaude.calls) == calls and guesses(108) == [("rules_v0", "other")]
    look("delete from prereg.steps where cost_usd = 3 returning 1")
    print("ok 7: at the $3 cap the worker stops; the baseline still guesses")

    # 8. rows and a file anchor in one run; the file's record is lost once and heals on the next run
    os.environ["ANCHOR_FILE"] = "README.md"
    real_record, lost = anchor.record, []

    def flaky_record(db, text, head, comment):
        if "kind=file" in text and not lost:
            lost.append(1)
            raise ConnectionError("simulated lost record after the comment was posted")
        real_record(db, text, head, comment)

    anchor.record = flaky_record
    try:
        anchor.main()
        raise AssertionError("expected the simulated failure")
    except ConnectionError:
        pass
    anchor.record, os.environ["ANCHOR_FILE"] = real_record, ""
    anchor.main()
    assert look("select count(*) from prereg.anchors")[0][0] == len(COMMENTS) == 3
    print("ok 8: a rows and a file anchor; the lost file record healed from GitHub")

    # 9. every comment recomputes from the ledger and the file, and every guess is covered
    with psycopg.connect(admin_url(), autocommit=True, row_factory=dict_row) as c:
        c.execute("set role prereg_owner")
        preds = c.execute(f"select {', '.join(FIELDS)} from prereg.predictions order by id").fetchall()
    prev, upto = GENESIS, 0
    for cm in COMMENTS:
        text, _, head = cm["body"].rpartition(" chain=")
        if " kind=rows " in text:
            last = int(text.split(" upto=")[1].split()[0])
            assert text == anchor_text([p for p in preds if upto < p["id"] <= last])
            upto = last
        else:
            assert text == file_text("README.md", hashlib.sha256(Path("README.md").read_bytes()).hexdigest(), "a" * 40)
        assert head == chain(prev, text)
        prev = head
    assert upto == preds[-1]["id"]
    assert "Magic login" not in json.dumps(look("select * from prereg.steps"), default=str)
    print(f"ok 9: {len(COMMENTS)} comments recompute and chain; all {len(preds)} guesses covered; no issue text in steps")

    def queue_directly(n, title, champion):  # a first sight from long ago, so the listing no longer shows it
        issue(n, title, minutes_ago=180)
        it = ISSUES[-1]
        with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:
            t.execute("select prereg.enqueue_issue(%s, now(), %s, '{}', %s, null)",
                      [n, content_sha256(it["title"], it["body"]), champion])

    def last_run():
        return look("select data->'champion' from prereg.run_events where kind = 'polled' order by id desc limit 1")[0][0]

    # 11. a failed GitHub read: the worker goes on to the next message, and the issue is guessed later
    queue_directly(110, "Login fails on Safari", champion_id)
    BROKEN.add(110)
    issue(111, "Login fails on Firefox", 0)
    tick()
    assert last_run()["unreachable"] == 1 and guesses(111)[-1] == (champion_id, "auth") and len(guesses(110)) == 0
    BROKEN.discard(110)
    time.sleep(1.1)  # the claimed message is hidden for worker.VT = 1 second
    tick()
    assert guesses(110) == [(champion_id, "auth")]
    print("ok 11: a failed GitHub read moves on to the next message; the issue is guessed on a later tick")

    # 12. a message queued for another champion gets no call
    queue_directly(112, "Login loops", "an-older-champion")
    calls = len(FakeClaude.calls)
    tick()
    assert last_run()["other_champion"] == 1 and len(guesses(112)) == 0
    assert not any("Login loops" in c for c in FakeClaude.calls[calls:])
    with psycopg.connect(admin_url(), autocommit=True) as c:  # take it out, so it cannot become a dead letter later
        c.execute("delete from pgmq.q_triage_events where message->>'issue_number' = '112'")
    print("ok 12: a message for another champion gets no call")

    # 10. GitHub is down: the run is recorded with the error, and the job fails
    DOWN[0] = True
    tick(fails=True)
    assert look("select data->>'http_status', data->>'error' from prereg.run_events where kind = 'polled'"
                " order by id desc limit 1") == [("503", "HTTPError")]
    print("ok 10: when GitHub is down, the run is recorded with its error, and the job fails")


if __name__ == "__main__":
    main()
