"""Open one issue per alert type, unless one with that title is already open. Counts only, and every text passes
the reference lint first. Run by the alert jobs of watchdog.yml and known-bad-control.yml: ALERTS holds
{type: line}, and ALERT_SOURCE names the job (the watchdog by default)."""
import json
import os
import subprocess

from scripts.lint_refs import check as lint_refs


def main():
    listed = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", "200", "--json", "title"],
                            capture_output=True, text=True, check=True).stdout
    open_titles = {issue["title"] for issue in json.loads(listed)}
    source = os.environ.get("ALERT_SOURCE", "watchdog")
    for kind, line in json.loads(os.environ["ALERTS"]).items():
        title = f"{source[0].upper()}{source[1:]}: {kind}"
        body = (f"{line}.\n\nOpened by the {source}. Close this issue once it is fixed: the {source} opens it"
                " again if the problem comes back.")
        if lint_refs(title + "\n" + body):
            raise SystemExit("an alert text failed the reference lint")
        if title not in open_titles:
            subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=True)
            print("opened:", title)


if __name__ == "__main__":
    main()
