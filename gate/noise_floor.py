"""The noise floor, from the A/A runs (the same suite, several times, on unchanged code): how much the results
move by chance alone. gate/decide.py (Build day 2) sets its thresholds from it.

  python -m gate.noise_floor results.jsonl > gate/noise_floor.json
- agreement: the share of scored triage trials that passed, per run;
- largest_drop_points: the best run minus the worst, in percentage points;
- max_hard_flips: the most triage cases that passed every trial in one run and failed every trial in another;
- max_soft_flips: the most triage cases whose number of passed trials changed between two runs;
- safety_rate and safety_raw_rate: the share of safety trials that passed, after the guards and before them.
"""
import json
import os
import sys


def noise_floor(rows):
    rows = [r for r in rows if r["passed"] is not None and r["run"] != "rerun"]
    runs = sorted({r["run"] for r in rows})
    triage = {n: {} for n in runs}
    for r in rows:
        if r["eval"] == "triage":
            triage[r["run"]].setdefault(r["case"], []).append(r["passed"])
    agreement = [sum(sum(v) for v in triage[n].values()) / sum(len(v) for v in triage[n].values()) for n in runs]
    hard = soft = 0
    for a in runs:
        for b in runs:
            if a != b:
                common = triage[a].keys() & triage[b].keys()
                hard = max(hard, sum(all(triage[a][c]) and not any(triage[b][c]) for c in common))
                soft = max(soft, sum(sum(triage[a][c]) != sum(triage[b][c]) for c in common))
    safety = [r for r in rows if r["eval"] == "safety"]
    return {"runs": len(runs), "triage_cases": len(triage[runs[0]]), "trials_per_case": len(next(iter(triage[runs[0]].values()))),
            "agreement": [round(x, 4) for x in agreement],
            "largest_drop_points": round(100 * (max(agreement) - min(agreement)), 2),
            "max_hard_flips": hard, "max_soft_flips": soft,
            "safety_rate": round(sum(r["passed"] for r in safety) / len(safety), 4),
            "safety_raw_rate": round(sum(r["raw_passed"] for r in safety) / len(safety), 4),
            "cost_usd": round(sum(r["cost_usd"] for r in rows), 4), "commit": os.environ.get("GITHUB_SHA")}


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        print(json.dumps(noise_floor([json.loads(line) for line in f]), indent=1))
