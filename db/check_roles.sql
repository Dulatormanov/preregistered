-- check_roles.sql: who may change the ledger. Every row must show ok = true.
-- Run as postgres in the Supabase SQL editor, after 001 and after any change to roles.
with t as (select oid, relname from pg_class where relnamespace = 'prereg'::regnamespace and relkind = 'r'),
     r as (select oid, rolname from pg_roles
           where rolname in ('postgres', 'triage_agent', 'anon', 'authenticated', 'service_role'))
select check_name, ok from (values
  ('1. postgres does not get prereg_owner''s or triage_agent''s rights by default',
   not pg_has_role('postgres', 'prereg_owner', 'USAGE') and not pg_has_role('postgres', 'triage_agent', 'USAGE')),
  ('2. postgres can still SET ROLE prereg_owner on purpose',
   pg_has_role('postgres', 'prereg_owner', 'SET')),
  ('3. no UPDATE, DELETE or TRUNCATE for: ' || (select string_agg(rolname, ', ' order by rolname) from r),
   not exists (select from t, r, unnest(array['UPDATE', 'DELETE', 'TRUNCATE']) as p(priv)
               where has_table_privilege(r.oid, t.oid, p.priv))),
  ('4. triage_agent cannot choose an id or a time',
   not exists (select from t join pg_attribute a on a.attrelid = t.oid
               where a.attname in ('id', 'created_at', 'first_seen_at')
                 and has_column_privilege('triage_agent', t.oid, a.attnum, 'INSERT'))),
  ('5. the API roles cannot read the ledger',
   not exists (select from t, r where r.rolname in ('anon', 'authenticated', 'service_role')
                                  and has_table_privilege(r.oid, t.oid, 'SELECT'))),
  ('6. triage_agent can add guesses',  -- by number: postgres may not look up names inside prereg
   exists (select from t join pg_attribute a on a.attrelid = t.oid
           where t.relname = 'predictions' and a.attname = 'area'
             and has_column_privilege('triage_agent', t.oid, a.attnum, 'INSERT')))
) as v(check_name, ok);
