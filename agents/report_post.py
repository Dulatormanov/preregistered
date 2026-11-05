"""The post job's last step (weekly.yml): add the agent's summary to the report only if it breaks none of the four
failure modes (agents/report_checks.py). Otherwise the report goes out with the numbers only, and says why.

  python -m agents.report_post report.md summary.txt data.json   (rewrites report.md)
"""
import json
import sys
from pathlib import Path

from agents.report_checks import check


def main():
    report, summary = Path(sys.argv[1]), Path(sys.argv[2]).read_text().strip()
    data = json.loads(Path(sys.argv[3]).read_text())
    broken = check(summary, data) if summary else ["no summary"]
    if broken:
        line = f"(The agent's summary was left out: it broke the check for {', '.join(broken)}.)"
    else:
        line = summary
    text = report.read_text().rstrip("\n").split("\n")
    report.write_text("\n".join(text[:1] + ["", line] + text[1:]) + "\n")
    print("summary:", "kept" if not broken else f"left out ({', '.join(broken)})")


if __name__ == "__main__":
    main()
