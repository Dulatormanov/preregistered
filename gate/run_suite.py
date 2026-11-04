"""Run an agent's suite (suites/<agent>.toml): every case of every eval, N trials each, into a results file.

  GATE_DB_URL=... ANTHROPIC_API_KEY=... PREREG_READ_TOKEN=... python -m gate.run_suite triage --runs 5 --out r.jsonl
  --baseline main.jsonl  A case that passed every trial there and fails every trial now (a hard flip) gets as
                         many trials again, so the gate (Build day 2) can tell a real loss from noise.
Every call goes through core/models.py as job 'gate' (its $12 a day cap) and is saved with record_gate_step.
A results line is one trial: codes and SHA-256 hashes only, never issue text or an answer. Each trial is scored
twice: after the guards (what counts) and before them (raw_passed, which shows what the guards catch).
Triage cases are read from GitHub with the read token, and skipped if their text changed since the golden set.
The log shows counts only.
"""
import argparse
import hashlib
import json
import os
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import anthropic
import psycopg
from psycopg.types.json import Jsonb

from agents import champion, guards
from core import contracts, models
from notary.canonical import content_sha256
from runner.poll import UPSTREAM, github

THREADS = 8
WAITS = (5, 20)  # seconds before each retry of an API error; after them the trial is an error, which is not scored


def sha256(text):
    return None if text is None else hashlib.sha256(text.encode()).hexdigest()


def read_case(case, token):
    """A sample case with its title and body from GitHub, or None if it is gone or its text changed."""
    try:
        it = github(f"{UPSTREAM}/{case['id']}", token)[1]
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return None
        raise
    if content_sha256(it["title"], it["body"]) != case["content_sha256"]:
        return None
    return dict(case, title=it["title"], body=it["body"])


def load(evals, token, pool):
    out, skipped = [], 0
    for name in evals:
        cases = contracts.cases(name)
        if cases and "title" not in cases[0]:
            cases = list(pool.map(lambda c: read_case(c, token), cases))
            skipped += cases.count(None)
        out += [(name, c) for c in cases if c is not None]
    return out, skipped


def trial(db, cfg, client, name, case, score, waits=WAITS):
    for wait in (*waits, None):
        text, h, step = models.answer_raw(db, "gate", cfg, client, case["title"], case["body"])
        db.execute("select prereg.record_gate_step('gate', %s, %s)",
                   [int(case["id"]) if case["id"].isdigit() else None, Jsonb(step)])
        if step["status"] != "error" or wait is None:
            break
        time.sleep(wait)
    guarded = text if text is not None and not guards.check(text, cfg["areas"]) else None
    passed, code = score(guarded, case)
    raw_passed, raw_code = score(text, case)
    error = step["status"] == "error"
    return {"eval": name, "case": case["id"], "status": step["status"], "passed": None if error else passed,
            "code": "error" if error else code, "raw_passed": None if error else raw_passed, "raw_code": raw_code,
            "input_sha256": h, "output_sha256": sha256(text), "cost_usd": float(step["cost_usd"])}


def hard_flips(baseline, rows):
    """(eval, case) pairs that passed every trial of the baseline and fail every trial now."""
    def by_case(rs):
        out = {}
        for r in rs:
            if r["passed"] is not None:
                out.setdefault((r["eval"], r["case"]), []).append(r["passed"])
        return out
    before, now = by_case(baseline), by_case(rows)
    return [k for k, v in now.items() if k in before and all(before[k]) and not any(v)]


def summary(rows):
    lines = []
    for run in sorted({r["run"] for r in rows}, key=str):
        rs = [r for r in rows if r["run"] == run]
        parts = []
        for name in dict.fromkeys(r["eval"] for r in rs):
            scored = [r for r in rs if r["eval"] == name and r["passed"] is not None]
            parts.append(f"{name} {sum(r['passed'] for r in scored)}/{len(scored)}"
                         f" (before the guards {sum(r['raw_passed'] for r in scored)})")
        errors = sum(r["passed"] is None for r in rs)
        lines.append(f"run {run}: {', '.join(parts)}, errors {errors}, cost ${sum(r['cost_usd'] for r in rs):.4f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline")
    a = ap.parse_args()
    m, cfg = contracts.manifest(a.agent), champion.load()
    scores = {name: contracts.scorer(name) for name in m["evals"]}
    client = anthropic.Anthropic(max_retries=0, timeout=60)
    with psycopg.connect(os.environ["GATE_DB_URL"], autocommit=True) as db, ThreadPoolExecutor(THREADS) as pool:
        cases, skipped = load(m["evals"], os.environ["PREREG_READ_TOKEN"], pool)
        print(f"{len(cases)} cases, {skipped} skipped (gone, or changed since the golden set)")

        def run(job):
            n, t, name, case = job
            return {"run": n, "trial": t, **trial(db, cfg, client, name, case, scores[name])}

        jobs = [(n, t, name, case) for n in range(1, a.runs + 1) for t in range(1, m["trials"] + 1)
                for name, case in cases]  # trial by trial, so a short API outage cannot take all trials of a case
        rows = list(pool.map(run, jobs))
        if a.baseline:
            with open(a.baseline) as f:
                flipped = set(hard_flips([json.loads(line) for line in f], rows))
            rows += list(pool.map(run, [("rerun", m["trials"] + t, name, case) for name, case in cases
                                         if (name, case["id"]) in flipped for t in range(1, m["trials"] + 1)]))
            print(f"hard flips re-run: {len(flipped)}")
    with open(a.out, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    print(summary(rows))


if __name__ == "__main__":
    main()
