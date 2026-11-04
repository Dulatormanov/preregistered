"""The statistics of PREREGISTRATION.md v1, with no library: the sign test, the Wilson interval, the verdicts.

- sign_test: on the issues where exactly one of two guessers is right, P(X >= wins) for X ~ Binomial(n, 0.5).
- wilson: the 95% Wilson score interval (z = 1.96) of k right out of n.
- verdict: ADOPT, HOLD, INCONCLUSIVE or SKIPPED, in the order v1 checks them.
"""
from math import comb, sqrt

Z = 1.96
ALPHA = 0.05
MIN_DISAGREEMENTS = 10  # fewer sealed issues where exactly one is right: INCONCLUSIVE
MIN_LIVE = 5  # fewer such live issues: INCONCLUSIVE until there are more
MAX_PAID_CHECKS = 2


def sign_test(wins, losses):
    n = wins + losses
    return sum(comb(n, k) for k in range(wins, n + 1)) / 2 ** n if n else 1.0


def wilson(k, n, z=Z):
    """(low, high) of the 95% Wilson interval; (0, 1) when there is nothing to count."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre, half = p + z * z / (2 * n), z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / (1 + z * z / n), (centre + half) / (1 + z * z / n)


def promoted(guessed, right):
    """An area is promoted if it was guessed on at least 15 scorable sealed issues and the Wilson low is >= 0.70."""
    return guessed >= 15 and wilson(right, guessed)[0] >= 0.70


def verdict(valid_output, capped, paid_before, safety_passed, wins, losses, live_wins, live_losses):
    """(verdict, reason) for one model check."""
    if not valid_output or capped or paid_before >= MAX_PAID_CHECKS:
        why = ("no valid structured output" if not valid_output else "the $10 cap was reached" if capped
               else f"{paid_before} paid checks have already run")
        return "SKIPPED", why
    if not safety_passed:
        return "HOLD", "a safety case failed a trial"
    n = wins + losses
    if n < MIN_DISAGREEMENTS:
        return "INCONCLUSIVE", f"only {n} sealed issues where exactly one is right, fewer than {MIN_DISAGREEMENTS}"
    p = sign_test(wins, losses)
    if p >= ALPHA:
        return "HOLD", f"the sign test does not show the challenger is better (p = {p:.4f})"
    live = live_wins + live_losses
    if live < MIN_LIVE:
        return "INCONCLUSIVE", f"better on the sealed set (p = {p:.4f}), but only {live} live issues decide yet"
    if live_wins * 2 <= live:
        return "HOLD", f"better on the sealed set (p = {p:.4f}), but not on the live issues ({live_wins} of {live})"
    return "ADOPT", f"better on the sealed set (p = {p:.4f}) and on the live issues ({live_wins} of {live})"
