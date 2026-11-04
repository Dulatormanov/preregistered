"""The drift check (Build day 2): the live database must still be what git says it is. Daily, as observer.

- privileges: every role's rights equal the matrix in credentials.toml (ops/privileges.py);
- functions: every prereg function's definition equals db/catalog.json, which is made from the migrations;
- schemas: net (it appears if pg_net is turned on) and pgmq_public (it appears if "Expose Queues via PostgREST"
  is turned on) must not exist.
  python -m ops.drift                  check OBSERVER_DB_URL; print one line per alert, and pass them on
  python -m ops.drift --write-catalog  write db/catalog.json from PREREG_TEST_ADMIN_URL (a test database)
  python -m ops.drift --check-catalog  fail if db/catalog.json differs from that test database (CI)
The catalog check runs in CI only on the functions: the test image may turn pg_net on by itself.
"""
import json
import os
import sys
from pathlib import Path

import psycopg

from ops.privileges import differences

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "db/catalog.json"
FUNCTIONS = """select p.oid::regprocedure::text, encode(sha256(convert_to(pg_get_functiondef(p.oid), 'UTF8')), 'hex')
               from pg_proc p where p.pronamespace = to_regnamespace('prereg') order by 1"""


def functions(c):
    """{signature: SHA-256 of its full definition} for every prereg function."""
    return dict(c.execute(FUNCTIONS).fetchall())


def check(c):
    """The alerts, as {type: one line}."""
    alerts = {}
    diff = differences(c)
    if diff:
        alerts["privileges"] = (f"{len(diff)} privileges differ from credentials.toml: "
                                + "; ".join(" ".join(x[:4]) for x in diff[:5]))
    live, want = functions(c), json.loads(CATALOG.read_text())
    changed = sorted(f for f in live.keys() | want.keys() if live.get(f) != want.get(f))
    if changed:
        alerts["functions"] = f"{len(changed)} prereg functions differ from db/catalog.json: {', '.join(changed[:5])}"
    for schema in ("net", "pgmq_public"):
        if c.execute("select to_regnamespace(%s) is not null", [schema]).fetchone()[0]:
            alerts[f"schema_{schema}"] = f"the schema {schema} exists on the live database"
    return alerts


def main():
    if "--write-catalog" in sys.argv or "--check-catalog" in sys.argv:
        with psycopg.connect(os.environ["PREREG_TEST_ADMIN_URL"], autocommit=True) as c:
            made = functions(c)
        if "--write-catalog" in sys.argv:
            CATALOG.write_text(json.dumps(made, indent=1, sort_keys=True) + "\n")
            print(f"wrote {len(made)} functions to db/catalog.json")
        elif made != json.loads(CATALOG.read_text()):
            sys.exit("db/catalog.json is out of date: run python -m ops.drift --write-catalog on a fresh test database")
        else:
            print(f"ok: db/catalog.json matches the {len(made)} functions the migrations make")
        return
    with psycopg.connect(os.environ["OBSERVER_DB_URL"], autocommit=True) as c:  # observer: reads only
        alerts = check(c)
    for line in alerts.values():
        print("ALERT", line)
    print(f"drift: {len(alerts)} alerts")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"alerts={json.dumps(alerts)}\n")


if __name__ == "__main__":
    main()
