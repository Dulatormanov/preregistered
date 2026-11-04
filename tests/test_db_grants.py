"""The grant test: each job role tries what it must never do, and must get error 42501 every time.

Run it after db/003_roles.sql (it needs the notary and observer roles). Until the Day 3 test database
exists, run it on your Mac against prereg-prod:
  TRIAGE_DB_URL=... NOTARY_DB_URL=... OBSERVER_DB_URL=... python tests/test_db_grants.py
Every attempt touches zero rows (WHERE false, or an empty table for TRUNCATE inside a rollback), so even
an attempt that is wrongly allowed changes nothing and uses no id. Each also runs in its own transaction,
which always rolls back. check_roles.sql covers what this test does not, from the catalog.
"""
import os

import psycopg

COLUMNS = {  # from db/001_ledger.sql and db/002_steps.sql; check_roles.sql reads the live catalog
    "issues_seen": ["issue_number", "gh_created_at", "content_sha256", "labels_at_seen", "first_seen_at"],
    "predictions": ["issue_number", "champion_id", "trial", "area", "needs_details", "input_sha256", "created_at"],
    "anchors": ["text", "chain_hash", "upto_prediction_id", "comment_id", "comment_created_at", "created_at"],
    "run_events": ["kind", "data", "created_at"],
    "steps": ["job", "issue_number", "champion_id", "model", "status", "request_id", "input_tokens",
              "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd", "lock_sha256", "error",
              "created_at"],
}
TIMED_INSERT = {  # an insert that also sets the row's time: no job may do it
    "issues_seen": "(issue_number, gh_created_at, content_sha256, labels_at_seen, first_seen_at)"
                   " select 1, now(), 'x', '{}', now()",
    "predictions": "(issue_number, champion_id, area, needs_details, input_sha256, created_at)"
                   " select 1, 'x', 'other', false, 'x', now()",
    "anchors": "(text, chain_hash, comment_id, comment_created_at, created_at) select 'x', 'x', 1, now(), now()",
    "run_events": "(kind, data, created_at) select 'x', '{}', now()",
    "steps": "(job, champion_id, model, status, lock_sha256, created_at) select 'x', 'x', 'x', 'ok', 'x', now()",
}
PLAIN_INSERT = {  # an insert with only the columns that some job may fill
    "issues_seen": "(issue_number, gh_created_at, content_sha256, labels_at_seen) select 1, now(), 'x', '{}'",
    "predictions": "(issue_number, champion_id, area, needs_details, input_sha256) select 1, 'x', 'other', false, 'x'",
    "anchors": "(text, chain_hash, comment_id, comment_created_at) select 'x', 'x', 1, now()",
    "run_events": "(kind, data) select 'x', '{}'",
    "steps": "(job, champion_id, model, status, lock_sha256) select 'x', 'x', 'x', 'ok', 'x'",
}
MAY_ADD = {"triage_agent": {"issues_seen", "predictions", "run_events", "steps"}, "notary": {"anchors"},
           "observer": set()}
ROLES = (("triage_agent", "TRIAGE_DB_URL"), ("notary", "NOTARY_DB_URL"), ("observer", "OBSERVER_DB_URL"))


def attempts(role):
    for table, columns in COLUMNS.items():
        for column in columns:
            yield f"update prereg.{table} set {column} = null where false"
        yield f"delete from prereg.{table} where false"
        yield f"truncate prereg.{table}"
        yield f"create trigger grant_probe before update on prereg.{table}" \
              " for each row execute function suppress_redundant_updates_trigger()"
        yield f"insert into prereg.{table} {TIMED_INSERT[table]} where false"
        if table not in MAY_ADD[role]:
            yield f"insert into prereg.{table} {PLAIN_INSERT[table]} where false"
    for other in ("prereg_owner", "postgres") + tuple(r for r, _ in ROLES if r != role):
        yield f"set role {other}"


def main():
    bad, n = [], 0
    for role, env in ROLES:
        with psycopg.connect(os.environ[env], autocommit=True, connect_timeout=20) as c:
            assert c.execute("select current_user").fetchone()[0] == role, env
            for sql in attempts(role):
                n += 1
                try:
                    with c.transaction(force_rollback=True):
                        c.execute(sql)
                    bad.append(f"{role}: ALLOWED: {sql}")
                except psycopg.errors.InsufficientPrivilege:
                    pass
                except psycopg.Error as e:
                    bad.append(f"{role}: {type(e).__name__} (not 42501): {sql}")
    print("\n".join(bad) if bad else f"ok: all {n} forbidden attempts were denied with 42501")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
