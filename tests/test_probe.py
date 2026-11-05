"""The probe's verdicts, with GitHub faked: only GitHub's own refusal is DENIED, and a write token that reaches a
job outside the environment fails the run. Run: python tests/test_probe.py"""
import contextlib
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probes import probe  # noqa: E402


def run(mode, answer, env):
    probe.call = lambda *args, **kw: answer
    os.environ.update(env)
    sys.argv = ["probe.py", mode]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            probe.main()
        except SystemExit as e:
            return e.code, out.getvalue()


def main():
    assert probe.result(200, "") == "LANDED"
    assert probe.result(403, "Resource not accessible by personal access token") == "DENIED"
    for status, message in ((401, "Bad credentials"), (403, "API rate limit exceeded for user"), (404, "Not Found"),
                            (422, "Validation Failed"), (502, ""), (0, "timeout")):
        assert probe.result(status, message) == "ERROR", (status, message)
    denied = (403, "req_1", "Resource not accessible by personal access token")
    assert run("read", denied, {"PREREG_READ_TOKEN": "x", "PREREG_SANDBOX_WRITE": ""})[0] == 0
    code, out = run("read", denied, {"PREREG_READ_TOKEN": "x", "PREREG_SANDBOX_WRITE": "s3cret"})
    assert code == 1 and "PRESENT (want ABSENT)" in out and "s3cret" not in out  # never printed
    assert run("read", (401, "req_2", "Bad credentials"), {"PREREG_SANDBOX_WRITE": ""})[0] == 1  # a dead token
    assert run("write", (200, "req_3", ""), {"PREREG_SANDBOX_WRITE": "s3cret"})[0] == 0
    # The promotion run's probes, against a fake sandbox where adding probe-side-door to issue 25 closes it.
    import probes.closure
    probes.closure.side_door_labels = lambda token: {"probe-side-door"}

    def sandbox(door_state="open", door_works=True, failing_polls=0):
        issues = {1: {"state": "open", "assignees": [], "milestone": None, "labels": []},
                  25: {"state": door_state, "assignees": [], "milestone": None, "labels": [], "closed_at": None,
                       "closed_by": None}}
        polls = [failing_polls]

        def fake_call(token, method, path, body=None):
            n = int(path.split("/")[2])
            if path.endswith("/assignees"):
                issues[n]["assignees"] = [{"login": a} for a in body["assignees"]] if method == "POST" else []
            elif path.endswith("/labels") and method == "POST":
                issues[n]["labels"] += [{"name": x} for x in body["labels"]]
                if "probe-side-door" in body["labels"] and door_works:
                    issues[n].update(state="closed", closed_at="2099-01-01T00:00:00Z", closed_by={"login": "github-actions[bot]"})
            elif "/labels/" in path and method == "DELETE":
                issues[n]["labels"] = [x for x in issues[n]["labels"] if x["name"] != path.rsplit("/", 1)[1]]
            elif method == "PATCH":
                issues[n]["state"] = body["state"]
            return 200, "req", ""

        def fake_issue(token, n):
            if n == 25 and polls[0] > 0 and issues[25]["labels"]:
                polls[0] -= 1
                raise TimeoutError("a slow poll")
            return issues[n]
        probe.call, probe.issue = fake_call, fake_issue
        return issues

    def run_probes():
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = probe.gateway_probes("token", wait=lambda: None, now=lambda: 0)
        return ok, out.getvalue()

    issues = sandbox()
    ok, out = run_probes()
    assert ok and out.count("REFUSED (want REFUSED)") == 4 and "unchanged (want unchanged)" in out, out
    assert issues[25]["state"] == "open" and issues[25]["labels"] == [] and issues[1]["assignees"] == []
    issues = sandbox(door_state="closed")  # left closed by an earlier run: no false LANDED, and nothing is sent to it
    ok, out = run_probes()
    assert not ok and "ERROR (want ready)" in out and "LANDED (want LANDED) | 200 | req |" not in out.split("side door")[-1]
    assert issues[25]["labels"] == []
    issues = sandbox(door_works=False)  # the side door no longer closes anything
    ok, out = run_probes()
    assert not ok and "after this label | ERROR (want LANDED)" in out and issues[25]["labels"] == []
    issues = sandbox(failing_polls=2)  # two polls time out: the probe goes on, and the undo still runs
    ok, out = run_probes()
    assert ok and issues[25]["state"] == "open" and issues[25]["labels"] == [], out
    print("ok: only a 403 refusal counts as DENIED, a write token outside the environment fails the probe, and the"
          " promotion probes report the gateway's refusals and the token's own reach")


if __name__ == "__main__":
    main()
