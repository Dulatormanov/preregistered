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
    print("ok: only a 403 refusal counts as DENIED, and a write token outside the environment fails the probe")


if __name__ == "__main__":
    main()
