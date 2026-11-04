"""The deterministic known-bad control: controls/known_bad.patch must still apply to main, and with it every
safety case must fail, even when the model gives a perfectly safe answer. No network and no database: it runs
the patched code in a temporary copy, with a fake Claude and a fake spend check. Run: python tests/test_known_bad.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import sys
from decimal import Decimal
from types import SimpleNamespace as NS
sys.path[:0] = [".", "tests"]
from agents import champion
from core import contracts
from gate.run_suite import trial
from test_champion import Fake, reply

db = NS(execute=lambda sql, args=None: NS(fetchone=lambda: (Decimal(0),)))
cfg, score = champion.load(), contracts.scorer("safety")
def safe(case):  # the honest answer, which follows no injection
    return Fake(reply('{"area": "%s", "needs_details": true}' % case["honest_area"]))
results = [trial(db, cfg, safe(case), "safety", case, score) for case in contracts.cases("safety")]
print(sum(r["passed"] for r in results), len(results))
'''


def run(where):
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=where, capture_output=True, text=True, check=True)
    return tuple(int(x) for x in out.stdout.split())


def main():
    assert run(ROOT) == (20, 20)  # without the patch, a safe answer passes every case
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "golden"))
        shutil.copytree(ROOT / "golden" / "v1", copy / "golden" / "v1")
        subprocess.run(["git", "apply", str(ROOT / "controls/known_bad.patch")], cwd=copy, check=True)
        assert run(copy) == (0, 20), "the known-bad patch no longer fails every safety case"
    print("ok: the known-bad patch applies to main, and fails all 20 safety cases whatever the model answers")


if __name__ == "__main__":
    main()
