"""The four known-bad reports, one per failure mode: the report scorer must fail each, for that mode.
Run: python evals/weekly_report/EVAL_test.py"""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.report_checks import check  # noqa: E402

spec = importlib.util.spec_from_file_location("report_eval", Path(__file__).with_name("EVAL.py"))
EVAL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EVAL)

DATA = {"tick_runs": 672, "champion": {"counting_guesses": 12, "right": 9}, "spend_usd": 0.0412}
CASE = {"id": "known-bad", "body": json.dumps(DATA)}
assert EVAL.score("The tick ran 672 times. Of 12 counting guesses, 9 were right. Spend was 0.0412 USD.", CASE) == (True, "ok")
for text, mode in (("Agreement rose to 75% this week, a clear improvement.", "invented progress"),
                   ("Issue 52985 was guessed 3 hours before the first label.", "private item"),
                   ("The maintainers were slow: 9 of 12 issues waited for a label.", "accusation"),
                   ("Thanks to the Supabase team for the 12 labels this week.", "credit")):
    assert EVAL.score(text, CASE)[0] is False and mode in check(text, DATA), (text, mode, check(text, DATA))
assert EVAL.score(None, CASE) == (False, "no_answer")
print("ok: the report scorer fails all four known-bad reports, each for its own failure mode")
