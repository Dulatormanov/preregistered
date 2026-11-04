"""Each cap of the model adapter (core/models.py), with fake spend and a fake Claude: no network, no database.

  python tests/test_budget.py
"""
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from agents import champion  # noqa: E402
from core import models  # noqa: E402
from test_champion import Fake, reply  # noqa: E402

CFG = champion.load()


class FakeDB:
    """Answers the spend functions with one fixed amount, and keeps the SQL it was asked."""
    def __init__(self, usd):
        self.usd, self.asked = Decimal(str(usd)), []

    def execute(self, sql, args):
        self.asked.append((sql, args))
        return NS(fetchone=lambda: (self.usd,))


def main():
    for job, cap, function in (("tick", 3, "spend_today"), ("gate", 12, "spend_today"),
                               ("check:claude-opus-5-5", 10, "spend_total")):
        under, at = FakeDB(cap - 0.01), FakeDB(cap)
        client = Fake(reply('{"area": "auth", "needs_details": false}'))
        assert models.answer(under, job, CFG, client, "Login fails", "body")[:2] == ("auth", False)
        assert under.asked == [(f"select prereg.{function}(%s)", [job])]
        client = Fake(reply('{"area": "auth", "needs_details": false}'))
        try:
            models.answer(at, job, CFG, client, "Login fails", "body")
            raise AssertionError(f"{job}: a call at the cap was made")
        except models.OverCap:
            assert not hasattr(client, "kw")  # the client was never called
    try:
        models.answer(FakeDB(0), "weekly", CFG, Fake(reply("{}")), "t", "b")
        raise AssertionError("a job with no cap got a call")
    except ValueError:
        pass
    area, _, _, step = models.answer(FakeDB(99), "tick", None, None, "Docker compose fails", "")
    assert (area, step) == ("self-hosted", None)  # rules_v0 is free: no cap, no step
    print("ok: each cap ($3 tick, $12 gate, $10 per model check) refuses the call at the cap, and only then")


if __name__ == "__main__":
    main()
