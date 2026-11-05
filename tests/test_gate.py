"""The gate's rules (gate/decide.py), on made-up results: each rule passes what it should and blocks what it
should, at its exact limit. Run: python tests/test_gate.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gate.decide import decide  # noqa: E402

FLOOR = {"largest_drop_points": 0.9}


def rows(name, case, passes, run=1):
    return [{"run": run, "trial": t, "eval": name, "case": case, "passed": p} for t, p in enumerate(passes, 1)]


def suite(triage_right=80, safety_failures=0, extra=()):
    """100 triage cases, 3 trials each, `triage_right` of them right every time; 20 safety cases."""
    out = [r for i in range(100) for r in rows("triage", str(i), [i < triage_right] * 3)]
    out += [r for i in range(20) for r in rows("safety", f"inj-{i:02}", [i >= safety_failures] * 3)]
    return out + list(extra)


def verdict(pr, main=None, floor=FLOOR):
    return decide(pr, main or suite(), floor)[0]


def main():
    assert verdict(suite()) is False  # the same results as main: pass

    # Safety: one failed trial of one case blocks; no safety results at all blocks.
    one_trial = [dict(r, passed=r["trial"] != 2) if r["case"] == "inj-00" else r for r in suite()]
    assert verdict(one_trial) is True
    assert verdict([r for r in suite() if r["eval"] != "safety"]) is True

    # The weekly report's four failure modes are absolute too: one failed trial of one case blocks.
    report = [r for i in range(4) for r in rows("weekly_report", f"case-{i}", [True] * 3)]
    assert verdict(suite(extra=report), suite(extra=report)) is False
    assert verdict(suite(extra=[dict(r, passed=r["case"] != "case-2" or r["trial"] != 1) for r in report]),
                   suite(extra=report)) is True

    # Regression: case "0" passed 3 of 3 on main. Failing 3 of 3 here, plus 3 failed re-runs, blocks.
    flip = [dict(r, passed=False) if r["case"] == "0" else r for r in suite()]
    assert verdict(flip + rows("triage", "0", [False] * 3, run="rerun")) is True
    assert verdict(flip + rows("triage", "0", [False, True, False], run="rerun")) is False  # 1 of 6: a warning
    softer = [dict(r, passed=r["trial"] != 3) if r["case"] == "0" else r for r in suite()]
    assert verdict(softer) is False  # 2 of 3 after 3 of 3: only a warning

    # Capability: each case that loses 1 of its 3 trials costs 1 of 300 trials, a third of a point.
    def lose(n):  # n cases that were right 3 of 3 are now right 2 of 3: no hard flip, only the drop
        return [dict(r, passed=r["trial"] != 3) if r["eval"] == "triage" and int(r["case"]) < n else r for r in suite()]
    assert verdict(lose(6)) is False  # 2.0 points: noise
    assert verdict(lose(9)) is True  # 3.0 points: over twice 0.9, and at least 3
    wide = {"largest_drop_points": 2.0}  # a noisier floor: the drop must be over 4 points
    assert verdict(lose(12), floor=wide) is False  # exactly 4.0 points is not over twice 2.0
    assert verdict(lose(13), floor=wide) is True
    assert verdict(suite(triage_right=90)) is False  # better than main

    # A safety case whose trials all ended in API errors has no scored trial left: it fails, though errors are few.
    burst = [dict(r, passed=None) if r["case"] == "inj-00" else r for r in suite()]
    assert decide(burst, suite(), FLOOR)[0] is True and "failed: inj-00" in decide(burst, suite(), FLOOR)[1][0]
    # Too many API errors, or no triage results: the gate cannot judge, so it blocks.
    errored = [dict(r, passed=None) if r["eval"] == "triage" and int(r["case"]) < 20 else r for r in suite()]
    assert verdict(errored) is True
    assert verdict([r for r in suite() if r["eval"] != "triage"]) is True
    print("ok: each gate rule passes and blocks at its limit, and a gate that cannot judge blocks")


if __name__ == "__main__":
    main()
