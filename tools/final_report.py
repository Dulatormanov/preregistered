"""The final report (DEVIATIONS.md, deviation 1): the live score from public data only, scored as make tables-public
scores it, once every window issue's labels are final: on or after 2026-11-21 00:00 UTC (the window's end plus the 7
days in which a label counts). The daily reveal job (reveal.yml) runs it after the verifier passes, and puts the
report on the data branch as reports/final.md, once. Before that date it writes nothing.

  GH_TOKEN=... python -m tools.final_report DATA_DIR OUT_DIR
Counts and rates only, never an issue number or text.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adopt.stats import wilson  # noqa: E402
from golden.truth import RULES, truth  # noqa: E402
from tools.tables import WINDOW, score  # noqa: E402

FINAL = WINDOW[1] + timedelta(days=RULES["window_days"])  # 2026-11-21 00:00 UTC
KEY = json.dumps(RULES, sort_keys=True)


def report(window, series, read_n, sealed, now):
    """The report's markdown, from tools.public_tables.public_window and results/sealed.json (None if not scored)."""
    rows = list(window.values())
    scorable = [r for r in rows if truth(r)[0] is not None]
    lines = ["Independent project, not affiliated with Supabase.", "", "# Final report: the live window", "",
             f"Issues created {WINDOW[0]:%Y-%m-%d} to {WINDOW[1] - timedelta(days=1):%Y-%m-%d} UTC, under"
             " PREREGISTRATION.md v1 and its deviation 1 (DEVIATIONS.md): a label counts if a human who is not the"
             f" issue's author added it within {RULES['window_days']} days, and a guess counts only if its anchor"
             " came before that label.", "",
             f"- **Window issues:** {len(rows)}, of which {len(scorable)} are scorable (they have a counting label).",
             "", "| Series | Agreement (95% Wilson interval) | Coverage | needs_details agreement |", "|---|---|---|---|"]
    for name, gs in series.items():
        total, have, right = score(gs, rows, RULES)
        counted = [(gs[r["number"]], r) for r in scorable
                   if r["number"] in gs and gs[r["number"]][1] < r["first_label_s"].get(KEY, float("inf"))]
        if not have:
            lines.append(f"| {name} | no counting guess | 0 of {total} | none |")
            continue
        low, high = wilson(right, have)
        nd = sum(g[2] == truth(r)[1] for g, r in counted)
        lines.append(f"| {name} | {right} of {have}, {right / have:.1%} ({low:.1%} to {high:.1%}) |"
                     f" {have} of {total}, {have / total:.0%} | {nd} of {len(counted)} |")
    lines += ["", "- **The sealed set** (151 older issues, guessed and scored once): " + (
        f"agreement {sealed['agreement']:.1%}; promoted areas: {', '.join(sealed['promoted']) or 'none'}."
        if sealed else "not scored yet."),
        "", f"Made on {now:%Y-%m-%d %H:%M} UTC by the daily reveal job, from {read_n} revealed guesses, the Notary log"
        " and GitHub's public label events. Check it from a clean clone: `make verify && make tables-public`."]
    return "\n".join(lines) + "\n"


def main():
    data, out = Path(sys.argv[1]), Path(sys.argv[2])
    now = datetime.now(timezone.utc)
    if now < FINAL:
        print(f"final report: not before {FINAL:%Y-%m-%d %H:%M} UTC, when the window's labels are final")
        return
    from tools.public_tables import public_window
    window, series, read_n = public_window(data, os.environ["GH_TOKEN"])
    sealed = ROOT / "results/sealed.json"
    text = report(window, series, read_n, json.loads(sealed.read_text()) if sealed.exists() else None, now)
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports/final.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
