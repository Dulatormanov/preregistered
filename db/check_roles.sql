-- check_roles.sql: who may change the ledger. Every row must show ok = true.
-- Run as postgres in the Supabase SQL editor, after each migration and after any change to roles.
-- Relations are found by number, not by name: postgres may not look up names inside prereg.
with t as (select oid, relname from pg_class where relnamespace = 'prereg'::regnamespace and relkind = 'r'),
     rel as (select oid from pg_class where relnamespace = 'prereg'::regnamespace and relkind in ('r', 'p', 'v', 'm', 'f')),
     job as (select oid, rolname from pg_roles where rolname in ('triage_agent', 'notary', 'observer')),
     r as (select oid, rolname from pg_roles
           where rolname in ('postgres', 'triage_agent', 'notary', 'observer', 'anon', 'authenticated', 'service_role')),
     adders as (select t.relname, array_agg(distinct r.rolname::text order by r.rolname::text) as roles
                from t join pg_attribute a on a.attrelid = t.oid and a.attnum > 0 and not a.attisdropped, r
                where has_column_privilege(r.oid, t.oid, a.attnum, 'INSERT') group by t.relname)
select check_name, ok from (values
  ('1. postgres does not get the rights of prereg_owner or of a job role by default',
   not exists (select from pg_roles x where x.rolname in ('prereg_owner', 'triage_agent', 'notary', 'observer')
               and pg_has_role('postgres', x.oid, 'USAGE'))),
  ('2. postgres can still SET ROLE prereg_owner on purpose',
   pg_has_role('postgres', 'prereg_owner', 'SET')),
  ('3. no UPDATE (of any column), DELETE, TRUNCATE or TRIGGER for: ' || (select string_agg(rolname, ', ' order by rolname) from r),
   not exists (select from rel, r where has_any_column_privilege(r.oid, rel.oid, 'UPDATE')
                                    or has_table_privilege(r.oid, rel.oid, 'DELETE, TRUNCATE, TRIGGER'))),
  ('4. no role can choose an id or a time',
   not exists (select from t join pg_attribute a on a.attrelid = t.oid, r
               where a.attname in ('id', 'created_at', 'first_seen_at')
                 and has_column_privilege(r.oid, t.oid, a.attnum, 'INSERT'))),
  ('5. the API roles cannot read any column of the ledger',
   not exists (select from rel, r where r.rolname in ('anon', 'authenticated', 'service_role')
                                    and has_any_column_privilege(r.oid, rel.oid, 'SELECT'))),
  ('6. only triage_agent adds issues, guesses, steps and run events; only notary adds anchors',
   coalesce((select array_agg(relname::text || ':' || array_to_string(roles, '+') order by relname) from adders), '{}')
   = array['anchors:notary', 'issues_seen:triage_agent', 'predictions:triage_agent', 'run_events:triage_agent',
           'steps:triage_agent']),
  ('7. observer can read every table',
   not exists (select from t where not has_table_privilege('observer', t.oid, 'SELECT'))),
  ('8. each job role: NOINHERIT, at most 2 connections, 30-second statement and idle timeouts, no override',
   (select count(*) from pg_roles x join job using (oid)
    where not x.rolinherit and x.rolconnlimit = 2
      and x.rolconfig @> array['statement_timeout=30s', 'idle_in_transaction_session_timeout=30s']) = 3
   and not exists (select from pg_db_role_setting s join job on s.setrole = job.oid where s.setdatabase <> 0)),
  ('9. no job role is a member of any role, so none can SET ROLE to borrow rights',
   not exists (select from pg_auth_members m join job on m.member = job.oid)),
  ('10. every prereg function runs as its owner with search_path = pg_catalog, pg_temp',
   not exists (select from pg_proc f where f.pronamespace = 'prereg'::regnamespace
               and not (f.prosecdef and coalesce(f.proconfig @> array['search_path=pg_catalog, pg_temp'], false)))),
  ('11. each job may call only its own functions',
   coalesce((select array_agg(f.proname::text || ':' || r.rolname::text order by f.proname::text, r.rolname::text)
             from pg_proc f, r where f.pronamespace = 'prereg'::regnamespace
             and has_function_privilege(r.oid, f.oid, 'EXECUTE')), '{}')
   = (case when not exists (select from pg_proc f where f.pronamespace = 'prereg'::regnamespace) then '{}'::text[] else array[
        'claim_next:triage_agent', 'complete:triage_agent', 'enqueue_issue:triage_agent', 'log_event:triage_agent',
        'recent_provider_failures:triage_agent', 'record_anchor:notary', 'record_failure:triage_agent'] end)),
  ('12. no job or API role can touch the queue tables directly',
   not exists (select from pg_class q, r where q.relnamespace = to_regnamespace('pgmq') and r.rolname <> 'postgres'
               and has_table_privilege(r.oid, q.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER')))
) as v(check_name, ok);
