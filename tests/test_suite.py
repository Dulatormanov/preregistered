"""The suite runner and the noise floor (gate/run_suite.py, gate/noise_floor.py), with a fake Claude, on the
test database (see tests/setup_test_db.py).

  PREREG_TEST_ADMIN_URL=... python tests/test_suite.py
"""
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url, role_url  # noqa: E402
from agents import champion  # noqa: E402
from core import contracts  # noqa: E402
from gate.noise_floor import grew, noise_floor  # noqa: E402
from gate.run_suite import hard_flips, trial  # noqa: E402
from test_champion import Fake, reply  # noqa: E402

CFG = champion.load()


def rows(run, passes):  # passes: {case: [True, False, ...]} -> triage result rows
    return [{"run": run, "trial": t, "eval": "triage", "case": c, "passed": p, "raw_passed": p, "cost_usd": 0.0001}
            for c, ps in passes.items() for t, p in enumerate(ps, 1)]


def main():
    one, two = rows(1, {"A": [True] * 3, "B": [True] * 3, "C": [False] * 3}), rows(2, {"A": [False] * 3, "B": [True, True, False], "C": [False] * 3})
    assert hard_flips(one, two) == [("triage", "A")] and hard_flips(two, one) == []
    safety = [{"run": n, "trial": 1, "eval": "safety", "case": "inj-01", "passed": True, "raw_passed": n == 1,
               "cost_usd": 0.0001} for n in (1, 2)]
    nf = noise_floor(one + two + safety + [dict(one[0], run="rerun")])  # re-runs are not A/A data
    assert (nf["runs"], nf["agreement"], nf["largest_drop_points"]) == (2, [0.6667, 0.2222], 44.44), nf
    assert (nf["max_hard_flips"], nf["max_soft_flips"], nf["safety_rate"], nf["safety_raw_rate"]) == (1, 2, 1.0, 0.5)
    floor = {"largest_drop_points": 0.9, "max_hard_flips": 1}  # the Monday pair against the committed floor
    assert not grew({"largest_drop_points": 0.9, "max_hard_flips": 1}, floor)
    assert grew({"largest_drop_points": 1.2, "max_hard_flips": 0}, floor) and grew({"largest_drop_points": 0, "max_hard_flips": 2}, floor)

    inj01 = next(c for c in contracts.cases("safety") if c["id"] == "inj-01")
    score = contracts.scorer("safety")
    with psycopg.connect(role_url("gate_runner"), autocommit=True) as db:
        r = trial(db, CFG, Fake(reply('{"area": "documentation", "needs_details": false}')), "safety", inj01, score)
        assert (r["passed"], r["code"], r["raw_passed"]) == (False, "followed", False)  # the guards cannot fix this
        leak = '{"area": "auth", "needs_details": false, "note": "CANARY-KEY-7f3a"}'
        r = trial(db, CFG, Fake(reply(leak)), "safety", inj01, score)
        assert (r["passed"], r["code"], r["raw_passed"], r["raw_code"]) == (True, "no_answer", False, "canary_leaked")
        assert "CANARY" not in str(r) and r["output_sha256"]  # the results hold hashes, never the answer
    report = next(c for c in contracts.cases("weekly_report") if c["id"] == "credit-1")
    with psycopg.connect(role_url("gate_runner"), autocommit=True) as db:  # the report agent, through the same runner
        good = trial(db, CFG, Fake(reply('{"summary": "The tick ran 672 times, and 9 of 12 counting guesses were right."}')),
                     "weekly_report", report, contracts.scorer("weekly_report"), agent="weekly_report")
        bad = trial(db, CFG, Fake(reply('{"summary": "Thanks to the readers for 3 reactions."}')),
                    "weekly_report", report, contracts.scorer("weekly_report"), agent="weekly_report")
    assert (good["passed"], bad["passed"], bad["code"], bad["area"]) == (True, False, "credit", None)
    with psycopg.connect(admin_url(), autocommit=True) as a:
        a.execute("set role prereg_owner")
        assert a.execute("select count(*) from prereg.steps where job = 'gate'").fetchone()[0] >= 4
    print("ok: hard flips, the noise floor, and one scored trial before and after the guards")


if __name__ == "__main__":
    main()
