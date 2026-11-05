-- 014_contacts.sql: the contact budget and the dead-letter redrive (Build day 7). Run once as `postgres`, then give
-- notifier and redriver passwords with scripts/role_password.py, then run check_roles.sql.
-- The jobs that post (alerts, the weekly report) log in as notifier; redrive.yml, which only main may run, as redriver.
begin;
set local createrole_self_grant = '';  -- as in 001: CREATE ROLE gives postgres no rights by surprise

create role notifier login;  -- spends from the contact budget, and nothing else
alter role notifier noinherit connection limit 2;
alter role notifier set statement_timeout = '30s';
alter role notifier set idle_in_transaction_session_timeout = '30s';
create role redriver login;  -- puts one dead letter back in the queue, as a logged event
alter role redriver noinherit connection limit 2;
alter role redriver set statement_timeout = '30s';
alter role redriver set idle_in_transaction_session_timeout = '30s';

set role prereg_owner;

-- Every message the project sends to a person. The unique key is the budget: one weekly report a week, one
-- approval request a day, and one comment per alert type per 6 hours. A second one in its window fails (23505).
create table prereg.contacts (
  id           bigint generated always as identity primary key,
  kind         text not null check (kind in ('weekly_report', 'approval_request', 'alert')),
  topic        text not null,  -- the alert type; empty for the others
  window_start timestamptz not null,
  created_at   timestamptz not null default clock_timestamp(),
  unique (kind, topic, window_start)
);

create function prereg.spend_contact(p_kind text, p_topic text)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.contacts (kind, topic, window_start)
  values (p_kind, coalesce(p_topic, ''), case p_kind collate "C"
    when 'weekly_report' then date_trunc('week', clock_timestamp(), 'UTC')
    when 'approval_request' then date_trunc('day', clock_timestamp(), 'UTC')
    when 'alert' then date_trunc('day', clock_timestamp(), 'UTC')
                      + interval '6 hours' * floor(extract(hour from clock_timestamp() at time zone 'UTC') / 6)
  end);
$$;

-- One dead letter back into the work queue, with a 'redriven' event. It returns false if there is no such letter.
-- A redriven message whose issue was first seen over 24 hours ago expires on its next read, and fails the tick.
create function prereg.redrive_dlq(p_msg_id bigint)
returns boolean language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
declare
  m record;
begin
  select * into m from pgmq.q_triage_dlq where msg_id = p_msg_id;
  if not found then
    return false;
  end if;
  perform pgmq.send('triage_events', m.message);
  perform pgmq.delete('triage_dlq', p_msg_id);
  insert into prereg.run_events (kind, data)
  values ('redriven', jsonb_build_object('dlq_msg_id', p_msg_id, 'issue_number', m.message->'issue_number'));
  return true;
end $$;

revoke execute on all functions in schema prereg from public;
grant usage on schema prereg to notifier, redriver;
grant execute on function prereg.spend_contact(text, text) to notifier, proposer;  -- proposer: the approval request
grant execute on function prereg.redrive_dlq(bigint), prereg.queue_health() to redriver;

reset role;
commit;
