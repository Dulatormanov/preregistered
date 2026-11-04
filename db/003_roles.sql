-- 003_roles.sql: one database login per job, and exactly what each may do. It replaces the Day 0 grants.
-- Run once as `postgres`. Then give notary and observer passwords with scripts/role_password.py,
-- and run check_roles.sql. Column INSERT rights stay until Day 5, when the jobs move onto functions.
begin;
set local createrole_self_grant = '';  -- as in 001: CREATE ROLE gives postgres no rights by surprise

create role notary login;    -- the anchor job: reads guesses, adds anchors
create role observer login;  -- reports, checks and exports: reads everything, writes nothing

-- Each job role: NOINHERIT, so it never uses another role's rights by default (it is a member of no
-- role, and check 9 keeps it so: NOINHERIT does not stop SET ROLE), and at most 2 connections.
-- The 30-second timeouts are session defaults: they stop a buggy job, not a leaked login, which could
-- change them. Check 8 alerts if they change. The jobs never keep a transaction open over the network.
alter role triage_agent noinherit connection limit 2;
alter role notary noinherit connection limit 2;
alter role observer noinherit connection limit 2;
alter role triage_agent set statement_timeout = '30s';
alter role triage_agent set idle_in_transaction_session_timeout = '30s';
alter role notary set statement_timeout = '30s';
alter role notary set idle_in_transaction_session_timeout = '30s';
alter role observer set statement_timeout = '30s';
alter role observer set idle_in_transaction_session_timeout = '30s';

set role prereg_owner;

-- Start from nothing: drop the Day 0 grants, and anything PUBLIC or the API roles could hold.
revoke all on schema prereg from public, anon, authenticated, service_role, triage_agent;
revoke all on all tables in schema prereg from public, anon, authenticated, service_role, triage_agent;
-- Day 3's functions start closed: nobody may call one until it is granted to one job.
alter default privileges revoke execute on functions from public;
-- New tables are readable by observer, and by nobody else until granted.
alter default privileges in schema prereg grant select on tables to observer;

grant usage on schema prereg to triage_agent, notary, observer;

-- triage_agent, the poll job: adds first sights, guesses, steps and run events, and reads what it needs.
grant select on prereg.issues_seen, prereg.predictions, prereg.steps, prereg.anchors to triage_agent;
grant insert (issue_number, gh_created_at, content_sha256, labels_at_seen) on prereg.issues_seen to triage_agent;
grant insert (issue_number, champion_id, trial, area, needs_details, input_sha256) on prereg.predictions to triage_agent;
grant insert (job, issue_number, champion_id, model, status, request_id, input_tokens, output_tokens,
              cache_read_tokens, cache_write_tokens, cost_usd, lock_sha256, error) on prereg.steps to triage_agent;
grant insert (kind, data) on prereg.run_events to triage_agent;

-- notary, the anchor job: reads the guesses and the anchors, and adds anchors only.
grant select on prereg.predictions, prereg.anchors to notary;
grant insert (text, chain_hash, upto_prediction_id, comment_id, comment_created_at) on prereg.anchors to notary;

-- observer: reads every table, and adds nothing.
grant select on all tables in schema prereg to observer;

reset role;
commit;
