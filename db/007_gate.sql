-- 007_gate.sql: the gate's login, and the reads the watchdog needs (Build day 1).
-- Run once as `postgres`, then give gate_runner a password with scripts/role_password.py, then run
-- check_roles.sql. The eval suites (gate/run_suite.py) log in as gate_runner; the watchdog logs in as observer.
begin;
set local createrole_self_grant = '';  -- as in 001: CREATE ROLE gives postgres no rights by surprise

create role gate_runner login;  -- the eval suites and the model check: their own spend and steps only
alter role gate_runner noinherit connection limit 2;
alter role gate_runner set statement_timeout = '30s';
alter role gate_runner set idle_in_transaction_session_timeout = '30s';

set role prereg_owner;

-- One model call of the gate or of a model check, as a step. The live job's steps go through complete() and
-- record_failure() instead, so the gate can never add to the live job's spend or look like a live guess.
create function prereg.record_gate_step(p_job text, p_issue_number int, p_step jsonb)
returns void language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
begin
  if p_job is null or not (p_job collate "C" = 'gate' or p_job collate "C" ~ '^check:[a-z0-9.-]{1,60}$') then
    raise exception 'record_gate_step takes job gate or check:<model>, not %', p_job using errcode = '22023';
  end if;
  perform prereg.save_step(p_job, p_issue_number, p_step);
end $$;

-- All the spend of one job, ever: the $10 cap of one model check (job 'check:<model>').
create function prereg.spend_total(p_job text)
returns numeric language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select coalesce(sum(cost_usd), 0) from prereg.steps where job = p_job collate "C";
$$;

-- For the watchdog: the dead letters waiting, and the age in seconds of the oldest message (0 if none).
create function prereg.queue_health(out dead_letters bigint, out oldest_message_s int)
language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select (select count(*) from pgmq.q_triage_dlq),
         coalesce((select extract(epoch from clock_timestamp() - min(enqueued_at))::int from pgmq.q_triage_events), 0);
$$;

revoke execute on all functions in schema prereg from public;
grant usage on schema prereg to gate_runner;
grant execute on function prereg.record_gate_step(text, int, jsonb), prereg.spend_today(text),
                          prereg.spend_total(text) to gate_runner;
grant execute on function prereg.queue_health() to observer;

reset role;
commit;
