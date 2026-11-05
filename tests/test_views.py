"""The value views (db/012_value_views.sql) on the test database, seeded through the job functions only.

  PREREG_TEST_ADMIN_URL=... python tests/test_views.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url, role_url  # noqa: E402

STEP = {"champion_id": "haiku55-p2", "model": "claude-haiku-5-5", "status": "ok", "request_id": "r",
        "input_tokens": 1000, "output_tokens": 16, "cost_usd": 0.0002, "lock_sha256": "x" * 64, "error": None}
NOW = datetime.now(timezone.utc)


def main():
    with psycopg.connect(admin_url(), autocommit=True) as a:
        a.execute("select pgmq.purge_queue('triage_events'), pgmq.purge_queue('triage_dlq')")
        a.execute("set role prereg_owner")
        a.execute("truncate prereg.outcomes, prereg.runs, prereg.steps, prereg.run_events, prereg.anchors,"
                  " prereg.predictions, prereg.issues_seen restart identity")
    created = NOW - timedelta(days=3)
    with psycopg.connect(role_url("triage_agent"), autocommit=True) as t:
        # 9305: a drill champion's guess is a series of its own, never 'champion' (PREREGISTRATION.md)
        for n, champion_area, champion_id in ((9301, "auth", "haiku55-p2"), (9302, "frontend", "haiku55-p2"),
                                              (9303, "auth", "haiku55-p2"), (9304, "auth", "haiku55-p2"),
                                              (9305, "auth", "haiku55-p2-drill")):
            t.execute("select prereg.enqueue_issue(%s, %s, 'h', '{}', %s, %s)",
                      [n, created, champion_id, Jsonb({"area": "other", "needs_details": False, "input_sha256": "h"})])
            attempt = t.execute("select * from prereg.claim_next(30, 'test')").fetchone()[0]
            t.execute("select prereg.complete(%s, 'guessed', %s, false, 'h', %s)",
                      [attempt, champion_area, Jsonb({**STEP, "champion_id": champion_id})])
    with psycopg.connect(role_url("notary"), autocommit=True) as n:  # one anchor covers all 10 guesses
        n.execute("select prereg.record_anchor('canon=v1 kind=rows upto=10 n=10 rows=x', 'chain-v', 10, 1, %s)",
                  [NOW - timedelta(days=2)])
    labels = [(9301, "auth", NOW - timedelta(days=1), "User", False),  # after the anchor: counts, and matches
              (9302, "studio", NOW - timedelta(days=1), "User", False),  # frontend: matches
              (9303, "studio", NOW - timedelta(days=2, hours=12), "User", False),  # before the anchor: not counted
              (9304, "auth", NOW - timedelta(days=1), "Bot", False),  # a bot: 9304 is not scorable
              (9305, "auth", NOW - timedelta(days=1), "User", False)]
    with psycopg.connect(role_url("collector"), autocommit=True) as k:
        for i, (n, label, at, actor, by_author) in enumerate(labels):
            k.execute("select prereg.record_outcome(%s, %s, %s, 'add', %s, %s, %s)", [n, f"e{i}", label, actor, by_author, at])
    with psycopg.connect(role_url("observer"), autocommit=True) as o:
        weekly = {series: (scorable, counting, matched) for _, series, scorable, counting, matched, _ in
                  o.execute("select * from prereg.v_agreement_weekly").fetchall()}
        assert weekly == {"champion": (3, 2, 2), "baseline": (4, 3, 0), "haiku55-p2-drill": (1, 1, 1)}, weekly
        cost = o.execute("select sum(cost_usd), sum(issues_guessed) from prereg.v_cost_per_issue").fetchone()
        assert float(cost[0]) == 0.001 and cost[1] == 5, cost
        work = o.execute("select matched_guesses, modelled_minutes, realised_minutes from prereg.v_work_absorbed_monthly").fetchall()
        assert work == [(2, None, 0)], work  # not timed yet: modelled minutes stay empty; 9305 is not 'champion'
    print("ok: the views count scorable, counting and matched guesses with the time rule, cost and modelled work")


if __name__ == "__main__":
    main()
