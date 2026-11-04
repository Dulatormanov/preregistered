"""The real privileges must equal the matrix in credentials.toml: no more, no less. Test database only.

  PREREG_TEST_ADMIN_URL=... python tests/test_privilege_matrix.py
It also applies tests/fixtures/bad_grant.sql, checks that the difference is caught, and removes it again.
"""
import sys
import tomllib
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from setup_test_db import admin_url  # noqa: E402

ROLES = ("triage_agent", "notary", "observer", "collector", "anon", "authenticated", "service_role", "postgres")
TABLE_RIGHTS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def expected():
    out = set()
    for role, p in tomllib.loads((ROOT / "credentials.toml").read_text())["privileges"].items():
        out |= {(role, "USAGE", s, "") for s in p.get("usage", [])}
        out |= {(role, "SELECT", t, "*") for t in p.get("select", [])}
        out |= {(role, "EXECUTE", f, "") for f in p.get("execute", [])}
        out |= {(role, "INSERT", t, col) for t, cols in p.get("insert", {}).items() for col in cols}
    return out


def actual(c):
    rels = c.execute("select oid, relname from pg_class where relnamespace = 'prereg'::regnamespace"
                     " and relkind in ('r', 'p', 'v', 'm', 'f')").fetchall()
    funcs = c.execute("select oid, proname from pg_proc where pronamespace = 'prereg'::regnamespace").fetchall()
    out = set()
    for role in ROLES:
        if c.execute("select has_schema_privilege(%s, 'prereg', 'USAGE')", [role]).fetchone()[0]:
            out.add((role, "USAGE", "prereg", ""))
        for oid, rel in rels:
            for right in TABLE_RIGHTS:
                if c.execute("select has_table_privilege(%s, %s::oid, %s)", [role, oid, right]).fetchone()[0]:
                    out.add((role, right, rel, "*"))
                elif right in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):  # rights that can be per column
                    out |= {(role, right, rel, col) for (col,) in c.execute(
                        "select attname from pg_attribute where attrelid = %s::oid and attnum > 0"
                        " and not attisdropped and has_column_privilege(%s, attrelid, attnum, %s)",
                        [oid, role, right]).fetchall()}
        out |= {(role, "EXECUTE", f, "") for oid, f in funcs
                if c.execute("select has_function_privilege(%s, %s::oid, 'EXECUTE')", [role, oid]).fetchone()[0]}
    return out


def differences(c):
    a, e = actual(c), expected()
    return sorted(("extra",) + x for x in a - e) + sorted(("missing",) + x for x in e - a)


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
    print("ok: the privileges equal credentials.toml, and the bad grant fixture is caught")


if __name__ == "__main__":
    main()
