"""The contracts of the eval suites (Build day 1): what an agent, a scorer and a suite are.

- An eval is a folder in evals/, laid out like supabase/evals: PROMPT.md (front matter, then the task), EVAL.py
  and EVAL_test.py. Its cases are either folders inside it, each with a PROMPT.md that holds the issue (safety),
  or the rows of the samples file that its PROMPT.md names (triage). The repo keeps no Supabase issue text, so
  those cases are read from GitHub at run time and must still match their content hash.
- A scorer is EVAL.py's score(text, case) -> (passed, code): text is the agent's raw answer, or None if it gave
  none (a refusal, or an answer the guards blocked). EVAL_test.py feeds it known-bad answers that must fail.
- An agent is a setup in models.lock, asked only through core/models.py.
- A suite manifest (suites/<agent>.toml) names the evals an agent must pass, and how many trials each case gets.
"""
import csv
import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def front_matter(path):
    """(the flat 'key: value' pairs between the --- lines, the rest of the file)."""
    m = re.match(r"---\n(.*?)\n---\n(.*)\Z", Path(path).read_text(), re.S)
    pairs = (line.split(":", 1) for line in m.group(1).splitlines())
    return {k.strip(): v.strip() for k, v in pairs}, m.group(2)


def manifest(agent):
    return tomllib.loads((ROOT / "suites" / f"{agent}.toml").read_text())


def scorer(name):
    """The score() function of evals/<name>/EVAL.py."""
    spec = importlib.util.spec_from_file_location(f"eval_{name}", ROOT / "evals" / name / "EVAL.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score


def cases(name):
    """The eval's cases, as dicts with an id; written cases also have their title and body."""
    meta, _ = front_matter(ROOT / "evals" / name / "PROMPT.md")
    if meta.get("samples"):
        with open(ROOT / meta["samples"], newline="") as f:
            return [dict(row, id=row["issue_number"]) for row in csv.DictReader(f)]
    out = []
    for path in sorted((ROOT / "evals" / name).glob("*/PROMPT.md")):
        case, text = front_matter(path)
        title, _, body = text.lstrip("\n").partition("\n")
        out.append(dict(case, id=path.parent.name, title=title.removeprefix("# "), body=body.strip("\n")))
    return out
