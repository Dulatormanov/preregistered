"""The only code that sends requests to GitHub with the sandbox write token. Two write routes and one read:
add one label to one sandbox issue, remove it again, and read an issue back. writes counts every write sent."""
import json
import urllib.error
import urllib.parse
import urllib.request

from gateway.payload import SANDBOX


class Transport:
    def __init__(self, token):
        self.token, self.writes = token, 0

    def call(self, method, path, body=None):
        """(HTTP status, GitHub's request id, the JSON answer or {})."""
        req = urllib.request.Request(
            f"https://api.github.com/repos/{SANDBOX}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "preregistered"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, r.headers.get("x-github-request-id"), json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("x-github-request-id"), {}

    def add_label(self, issue, label):
        self.writes += 1
        return self.call("POST", f"/issues/{int(issue)}/labels", {"labels": [label]})

    def remove_label(self, issue, label):
        self.writes += 1
        return self.call("DELETE", f"/issues/{int(issue)}/labels/{urllib.parse.quote(label, safe='')}")

    def read_issue(self, issue):
        return self.call("GET", f"/issues/{int(issue)}")
