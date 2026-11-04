"""The real privileges must equal the matrix in credentials.toml: no more, no less. Test database only.

  PREREG_TEST_ADMIN_URL=... python tests/test_privilege_matrix.py
It looks at every role except superusers, prereg_owner (the owner) and the pg_* roles: schema rights on prereg
and pgmq, every right on every prereg table, column, sequence and function, and every write right on pgmq.
Then it applies tests/fixtures/bad_grant.sql, checks that the difference is caught, and removes it again.
"""
import sys
import tomllib
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from setup_test_db import admin_url  # noqa: E402

TABLE_RIGHTS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER", "MAINTAIN")
COLUMN_RIGHTS = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
QUEUE_WRITES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "MAINTAIN")  # reads of pgmq are not tracked


def names(c, sql, args=None):
    return [n for (n,) in c.execute(sql, args).fetchall()]


def objects(c):
    rel = "select relname from pg_class where relnamespace = to_regnamespace('{}') and relkind in ({}) order by 1"
    return {"tables": names(c, rel.format("prereg", "'r', 'p', 'v', 'm', 'f'")),
            "sequences": names(c, rel.format("prereg", "'S'")),
            "queue": names(c, rel.format("pgmq", "'r', 'p', 'v', 'm', 'f', 'S'")),
            "roles": names(c, "select rolname from pg_roles where not rolsuper and rolname <> 'prereg_owner'"
                              " and rolname !~ '^pg_' order by 1")}


def expected(o):
    out = set()
    for role, p in tomllib.loads((ROOT / "credentials.toml").read_text())["privileges"].items():
        out |= {(role, "USAGE", s, "") for s in p.get("usage", [])}
        out |= {(role, "CREATE", s, "") for s in p.get("create", [])}
        out |= {(role, "SELECT", t, "*") for t in (o["tables"] if p.get("select") == ["*"] else p.get("select", []))}
        out |= {(role, "SEQ SELECT", q, "") for q in (o["sequences"] if p.get("sequence_select") == ["*"]
                                                      else p.get("sequence_select", []))}
        out |= {(role, "EXECUTE", f, "") for f in p.get("execute", [])}
        out |= {(role, "INSERT", t, col) for t, cols in p.get("insert", {}).items() for col in cols}
    return out


def actual(c, o):
    def has(sql, *args):
        return c.execute(sql, args).fetchone()[0]

    funcs = names(c, "select proname from pg_proc where pronamespace = 'prereg'::regnamespace order by 1")
    out = set()
    for role in o["roles"]:
        for schema in ("prereg", "pgmq"):
            for right in ("USAGE", "CREATE"):
                if has("select has_schema_privilege(%s, to_regnamespace(%s), %s)", role, schema, right):
                    out.add((role, right, schema, ""))
        for rel in o["tables"]:
            oid = f"prereg.{rel}"
            for right in TABLE_RIGHTS:
                if has("select has_table_privilege(%s, %s::regclass, %s)", role, oid, right):
                    out.add((role, right, rel, "*"))
                elif right in COLUMN_RIGHTS:
                    out |= {(role, right, rel, col) for col in names(
                        c, "select attname from pg_attribute where attrelid = %s::regclass and attnum > 0"
                           " and not attisdropped and has_column_privilege(%s, attrelid, attnum, %s)",
                        [oid, role, right])}
        for seq in o["sequences"]:
            for right in ("USAGE", "SELECT", "UPDATE"):
                if has("select has_sequence_privilege(%s, %s::regclass, %s)", role, f"prereg.{seq}", right):
                    out.add((role, f"SEQ {right}", seq, ""))
        out |= {(role, "EXECUTE", f, "") for f in funcs
                if has("select has_function_privilege(%s, (select oid from pg_proc where proname = %s"
                       " and pronamespace = 'prereg'::regnamespace), 'EXECUTE')", role, f)}
        if role != "postgres":  # postgres made the queue tables: it owns them
            for q in o["queue"]:
                for right in QUEUE_WRITES:
                    if has("select has_table_privilege(%s, %s::regclass, %s)", role, f"pgmq.{q}", right) or (
                            right in COLUMN_RIGHTS and has("select has_any_column_privilege(%s, %s::regclass, %s)",
                                                           role, f"pgmq.{q}", right)):
                        out.add((role, right, f"pgmq.{q}", ""))
    return out


def differences(c):
    o = objects(c)
    a, e = actual(c, o), expected(o)
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
    print("ok: the privileges of every role equal credentials.toml, and the bad grant fixture is caught")


if __name__ == "__main__":
    main()
