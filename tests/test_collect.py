"""The outcomes collector's GraphQL read (outcomes/collect.py), with GitHub faked: a failed reply fails the run,
so it cannot pass for a day with no new labels, and a deleted issue is still fine. Run: python tests/test_collect.py"""
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PREREG_READ_TOKEN", "x")
from outcomes import collect  # noqa: E402


def reply(body):
    urllib.request.urlopen = lambda req, timeout=None: io.BytesIO(json.dumps(body).encode())


def main():
    reply({"data": {"repository": {"i1": None}}, "errors": [{"type": "NOT_FOUND"}]})  # a deleted issue
    assert collect.query([1]) == {"i1": None}
    for body in ({"data": None, "errors": [{"type": "RATE_LIMITED", "message": "issue 1"}]},
                 {"data": {"repository": None}}, {"errors": [{"type": "INTERNAL"}]}):
        reply(body)
        try:
            collect.query([1])
            raise AssertionError(f"a failed reply passed: {body}")
        except SystemExit as e:
            assert "issue 1" not in str(e)  # error types and counts only: the log is public
    print("ok: a failed GraphQL reply fails the collector, and a deleted issue does not")


if __name__ == "__main__":
    main()
