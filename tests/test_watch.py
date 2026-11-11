"""The model watcher's pure parts (adopt/watch.py, adopt/check.py). Run: python tests/test_watch.py"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adopt.check import challenger, compare, render  # noqa: E402
from adopt.watch import candidates  # noqa: E402
from agents import champion  # noqa: E402
from scripts.lint_refs import check as lint_refs  # noqa: E402


def model(id_, day):
    return NS(id=id_, created_at=datetime(2026, 11, day, tzinfo=timezone.utc))


def main():
    new = [model("claude-sonnet-5-5", 1), model("claude-haiku-5-5", 3), model("claude-opus-6", 4), model("gpt-x", 5)]
    assert candidates(new, "claude-haiku-5-5") == ["claude-opus-6", "claude-sonnet-5-5"]  # newest first, no champion
    # wins: the challenger is right where the incumbent is wrong; losses: the reverse; both right or both wrong: neither
    cases = {1: "auth", 2: "auth", 3: "frontend", 4: "other"}
    assert compare(cases, {1: "auth", 2: "other", 3: "auth", 4: "auth"}, {1: "auth", 2: "auth", 3: "auth", 4: "other"}) == (2, 0)
    assert compare(cases, {1: "auth"}, {1: "other"}) == (0, 1)
    cfg = champion.load()
    assert challenger(cfg, "claude-unknown-9")["prices"] is None  # no price: the check is SKIPPED
    assert challenger(cfg, "claude-haiku-5-5")["c"]["model"] == "claude-haiku-5-5"
    text = render({"model": "m", "dry_run": True, "verdict": "INCONCLUSIVE", "reason": "r", "hours": 1.0,
                   "safety": "20 of 20", "set": "s", "incumbent": "rules_v0", "wins": 3, "losses": 1, "p": 2.9e-09,
                   "live": "0 of 0", "cost": 0.01, "cost_per_100": 0.02})
    assert "INCONCLUSIVE" in text and "(dry run)" in text and "p = 2.9e-09" in text and not lint_refs(text)
    text = render({"model": "m", "dry_run": False, "verdict": "SKIPPED", "reason": "r", "hours": 0.0,
                   "safety": "not run", "set": "nothing (skipped)", "incumbent": "incumbent", "wins": 0, "losses": 0,
                   "p": 1.0, "live": "0 of 0", "cost": 0.0, "cost_per_100": None})
    assert "| Cost | no calls; $0.0 for this check |" in text, text  # was "$None per 100 issues"
    print("ok: the watcher picks new Claude models, the check counts wins and losses, and the verdict renders")


if __name__ == "__main__":
    main()
