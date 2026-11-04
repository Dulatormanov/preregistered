"""Every privilege that matters, read from the catalog, and the matrix in credentials.toml it must equal.

Used by tests/test_privilege_matrix.py (the test database, in CI) and by ops/drift.py (prereg-prod, daily, as
observer). It looks at every role except superusers, prereg_owner (the owner) and the pg_* roles: schema rights
on prereg and pgmq, every right on every prereg table, column, sequence and function, and every write right on
the queue tables. It is one query, and it finds objects by number, not by name, so a role without USAGE on pgmq
can run it too.
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTUAL = """
with roles as (select rolname from pg_roles where not rolsuper and rolname <> 'prereg_owner' and rolname !~ '^pg_'),
     rel as (select oid, relname from pg_class where relnamespace = to_regnamespace('prereg')
             and relkind in ('r', 'p', 'v', 'm', 'f')),
     seq as (select oid, relname from pg_class where relnamespace = to_regnamespace('prereg') and relkind = 'S'),
     queue as (select oid, relname from pg_class where relnamespace = to_regnamespace('pgmq')
               and relkind in ('r', 'p', 'v', 'm', 'f', 'S')),
     fn as (select oid, proname from pg_proc where pronamespace = to_regnamespace('prereg'))
select r.rolname, x.right_, s.schema_, '' from roles r, (values ('prereg'), ('pgmq')) s(schema_),
  (values ('USAGE'), ('CREATE')) x(right_) where has_schema_privilege(r.rolname, to_regnamespace(s.schema_), x.right_)
union all
select r.rolname, x.right_, t.relname, '*' from roles r, rel t,
  unnest(array['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) x(right_)
  where has_table_privilege(r.rolname, t.oid, x.right_)
union all  -- a column right counts only where the whole-table right is missing
select r.rolname, x.right_, t.relname, a.attname from roles r, rel t
  join pg_attribute a on a.attrelid = t.oid and a.attnum > 0 and not a.attisdropped,
  unnest(array['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']) x(right_)
  where not has_table_privilege(r.rolname, t.oid, x.right_) and has_column_privilege(r.rolname, t.oid, a.attnum, x.right_)
union all
select r.rolname, 'SEQ ' || x.right_, q.relname, '' from roles r, seq q, unnest(array['USAGE', 'SELECT', 'UPDATE']) x(right_)
  where has_sequence_privilege(r.rolname, q.oid, x.right_)
union all
select r.rolname, 'EXECUTE', f.proname, '' from roles r, fn f where has_function_privilege(r.rolname, f.oid, 'EXECUTE')
union all  -- postgres made the queue tables, so it owns them; reads of pgmq are not tracked
select r.rolname, x.right_, 'pgmq.' || q.relname, '' from roles r, queue q,
  unnest(array['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'TRIGGER', 'MAINTAIN']) x(right_)
  where r.rolname <> 'postgres' and (has_table_privilege(r.rolname, q.oid, x.right_)
        or (x.right_ in ('INSERT', 'UPDATE') and has_any_column_privilege(r.rolname, q.oid, x.right_)))
"""


def actual(c):
    return {tuple(row) for row in c.execute(ACTUAL).fetchall()}


def expected(c):
    def names(kinds):
        return [n for (n,) in c.execute("select relname from pg_class where relnamespace = to_regnamespace('prereg')"
                                        " and relkind = any(%s)", [kinds]).fetchall()]
    tables, sequences = names(["r", "p", "v", "m", "f"]), names(["S"])
    out = set()
    for role, p in tomllib.loads((ROOT / "credentials.toml").read_text())["privileges"].items():
        out |= {(role, "USAGE", s, "") for s in p.get("usage", [])}
        out |= {(role, "CREATE", s, "") for s in p.get("create", [])}
        out |= {(role, "SELECT", t, "*") for t in (tables if p.get("select") == ["*"] else p.get("select", []))}
        out |= {(role, "SEQ SELECT", q, "") for q in (sequences if p.get("sequence_select") == ["*"]
                                                      else p.get("sequence_select", []))}
        out |= {(role, "EXECUTE", f, "") for f in p.get("execute", [])}
        out |= {(role, "INSERT", t, col) for t, cols in p.get("insert", {}).items() for col in cols}
    return out


def differences(c):
    a, e = actual(c), expected(c)
    return sorted(("extra",) + x for x in a - e) + sorted(("missing",) + x for x in e - a)
