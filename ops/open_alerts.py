"""Open one issue per alert type, or comment on the one that is open, within the contact budget: at most one new
issue or comment per alert type per 6 hours (ops/notify.py). Counts only, and every text passes the reference lint
first. Run by the alert jobs: ALERTS holds {type: line}, and ALERT_SOURCE names the job (the watchdog by default)."""
import json
import os
import subprocess

from ops.notify import spend
from scripts.lint_refs import check as lint_refs


def main():
    listed = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", "200", "--json", "number,title"],
                            capture_output=True, text=True, check=True).stdout
    open_issues = {issue["title"]: issue["number"] for issue in json.loads(listed)}
    source = os.environ.get("ALERT_SOURCE", "watchdog")
    alerts = json.loads(os.environ.get("ALERTS") or "{}") or {"did_not_run": f"the {source} did not finish"}
    for kind, line in alerts.items():
        title = f"{source[0].upper()}{source[1:]}: {kind}"
        body = (f"{line}.\n\nOpened by the {source}. Close this issue once it is fixed: the {source} opens it"
                " again if the problem comes back.")
        if lint_refs(title + "\n" + body):
            raise SystemExit("an alert text failed the reference lint")
        if not spend("alert", title):
            print("over the contact budget, not sent:", title)
        elif title in open_issues:
            subprocess.run(["gh", "issue", "comment", str(open_issues[title]), "--body", f"Still true: {line}."], check=True)
            print("commented:", title)
        else:
            subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=True)
            print("opened:", title)


if __name__ == "__main__":
    main()
