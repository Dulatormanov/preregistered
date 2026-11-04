"""Known-bad answers that the triage scorer must fail. Run: python evals/triage/EVAL_test.py"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("triage_eval", Path(__file__).with_name("EVAL.py"))
EVAL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EVAL)

CASE = {"id": "1", "area": "auth"}
assert EVAL.score('{"area": "auth", "needs_details": true}', CASE) == (True, "ok")
assert EVAL.score('{"area": "frontend", "needs_details": false}', CASE) == (False, "wrong_area")
assert EVAL.score('{"area": "auth"', CASE) == (False, "invalid")  # cut off
assert EVAL.score('["auth"]', CASE) == (False, "invalid")
assert EVAL.score(None, CASE) == (False, "no_answer")  # refused, or blocked by the guards
print("ok: the triage scorer fails every known-bad answer")
