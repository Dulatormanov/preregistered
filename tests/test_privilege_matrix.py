"""The real privileges must equal the matrix in credentials.toml: no more, no less. Test database only.

  PREREG_TEST_ADMIN_URL=... python tests/test_privilege_matrix.py
The comparison is ops/privileges.py, which ops/drift.py also runs daily on prereg-prod. This test then applies
tests/fixtures/bad_grant.sql, checks that the difference is caught, and removes it again.
"""
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url  # noqa: E402
from ops.privileges import differences  # noqa: E402


def main():
    with psycopg.connect(admin_url(), autocommit=True) as c:
        diff = differences(c)
        assert not diff, "\n".join(map(str, diff))
        c.execute((ROOT / "tests/fixtures/bad_grant.sql").read_text())
        try:
            assert ("extra", "triage_agent", "UPDATE", "predictions", "*") in differences(c), "bad grant not caught"
        finally:
            c.execute("set role prereg_owner; revoke update on prereg.predictions from triage_agent; reset role")
        assert not differences(c)
    print("ok: the privileges of every role equal credentials.toml, and the bad grant fixture is caught")


if __name__ == "__main__":
    main()
