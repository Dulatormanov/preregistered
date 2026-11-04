-- 005_outcomes.sql: the human labels that later decide whether a guess was right (Day 4).
-- Run once as `postgres`, then give collector a password with scripts/role_password.py, then run
-- check_roles.sql. The daily outcomes job (outcomes/collect.py) logs in as collector.
begin;
set local createrole_self_grant = '';  -- as in 001: CREATE ROLE gives postgres no rights by surprise

create role collector login;  -- the daily outcomes job: adds label events through record_outcome only
alter role collector noinherit connection limit 2;
alter role collector set statement_timeout = '30s';
alter role collector set idle_in_transaction_session_timeout = '30s';

set role prereg_owner;

-- One row per label event on a seen issue, as GitHub's timeline shows it. Never a login: only the actor's type.
create table prereg.outcomes (
  id           bigint generated always as identity primary key,
  issue_number int not null references prereg.issues_seen,
  event_key    text not null unique,  -- sha256 of GitHub's event id, so each event is saved once
  label        text not null,
  action       text not null check (action in ('add', 'remove')),
  actor        text not null,         -- User, Bot, Mannequin or Ghost
  by_author    boolean not null,      -- the actor opened the issue
  labeled_at   timestamptz not null,  -- GitHub's time for the event
  created_at   timestamptz not null default clock_timestamp()
);

-- True if the event is new, null if it was saved before.
create function prereg.record_outcome(p_issue_number int, p_event_key text, p_label text, p_action text,
                                      p_actor text, p_by_author boolean, p_labeled_at timestamptz)
returns boolean language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.outcomes (issue_number, event_key, label, action, actor, by_author, labeled_at)
  values (p_issue_number, p_event_key, p_label, p_action, p_actor, p_by_author, p_labeled_at)
  on conflict (event_key) do nothing
  returning true;
$$;

revoke execute on function prereg.record_outcome(int, text, text, text, text, boolean, timestamptz) from public;
grant usage on schema prereg to collector;
grant select on prereg.issues_seen to collector;  -- which issues to look at
grant execute on function prereg.record_outcome(int, text, text, text, text, boolean, timestamptz) to collector;

reset role;
commit;
