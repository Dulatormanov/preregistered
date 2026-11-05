"""adopt/stats.py against values worked out by hand. Run: python tests/test_stats.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adopt.stats import promoted, sign_test, verdict, wilson  # noqa: E402


def close(a, b):
    return abs(a - b) < 1e-4


def main():
    # Sign test: P(X >= w) for X ~ Binomial(n, 1/2), counted by hand from Pascal's triangle.
    assert close(sign_test(9, 1), 11 / 1024)  # C(10,9) + C(10,10) = 10 + 1
    assert close(sign_test(8, 2), 56 / 1024)  # 45 + 10 + 1: just over 0.05
    assert close(sign_test(5, 5), 638 / 1024)  # 252 + 210 + 120 + 45 + 10 + 1
    assert sign_test(0, 0) == 1.0 and sign_test(3, 0) == 1 / 8
    # Wilson, z = 1.96: (p + z^2/2n -+ z sqrt(p(1-p)/n + z^2/4n^2)) / (1 + z^2/n)
    assert close(wilson(14, 15)[0], 0.70178) and close(wilson(13, 15)[0], 0.62121) and close(wilson(15, 15)[0], 0.79612)
    assert wilson(0, 0) == (0.0, 1.0)
    # The promotion bar: with 15 guesses, 14 must be right.
    assert promoted(15, 14) and not promoted(15, 13) and not promoted(14, 14)
    # The verdicts, in v1's order.
    v = lambda **kw: verdict(**{"valid_output": True, "capped": False, "paid_before": 0, "safety_passed": True,  # noqa: E731
                                "wins": 9, "losses": 1, "live_wins": 4, "live_losses": 1, **kw})[0]
    assert v() == "ADOPT"
    assert v(valid_output=False) == v(capped=True) == v(paid_before=2) == "SKIPPED"
    assert v(safety_passed=False) == "HOLD"
    assert v(wins=6, losses=3) == "INCONCLUSIVE"  # 9 disagreements
    assert v(wins=8, losses=2) == "HOLD"  # p = 0.0547
    assert v(live_wins=3, live_losses=1) == "INCONCLUSIVE"  # 4 live issues
    assert v(live_wins=3, live_losses=3) == "HOLD"  # half is not more than half
    assert "the dev set" in verdict(True, False, 0, True, 9, 1, 0, 0, where="the dev set")[1]
    print("ok: the sign test, the Wilson interval, the promotion bar and the verdicts match the hand values")


if __name__ == "__main__":
    main()
