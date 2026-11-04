-- 010_adopt.sql: the model watcher and the sealed score (Build day 4). Run once as `postgres`, then give adopter
-- a password with scripts/role_password.py, then run check_roles.sql. The watcher (watch.yml) and the one sealed
-- run (sealed.yml) log in as adopter; its secret lives in the environment `adopt`, which only main may use.
begin;
set local createrole_self_grant = '';  -- as in 001: CREATE ROLE gives postgres no rights by surprise

create role adopter login;  -- the model watcher: models it saw, challenger guesses, verdicts, the sealed run
alter role adopter noinherit connection limit 2;
alter role adopter set statement_timeout = '30s';
alter role adopter set idle_in_transaction_session_timeout = '30s';

set role prereg_owner;

-- Every model the watcher has seen in Anthropic's model list, and when it first saw it.
create table prereg.models_seen (
  model_id         text primary key,
  display_name     text,
  model_created_at timestamptz,  -- Anthropic's own date for the model
  first_seen_at    timestamptz not null default clock_timestamp()
);

-- The champion's one guess per sealed issue. The primary key is the run-once rule: a second run fails (23505).
create table prereg.sealed_guesses (
  issue_number  int primary key,
  champion_id   text not null,
  status        text not null check (status in ('ok', 'refused', 'invalid', 'error')),
  area          text,  -- null unless status is 'ok'
  needs_details boolean,
  input_sha256  text not null,
  created_at    timestamptz not null default clock_timestamp()
);

-- A challenger's guesses in one model check. Each check guesses each case once.
create table prereg.challenger_results (
  id            bigint generated always as identity primary key,
  check_id      text not null,
  model_id      text not null,
  issue_set     text not null check (issue_set in ('sealed', 'dev', 'live', 'safety')),
  case_key      text not null,  -- an issue number, or a safety case id
  status        text not null check (status in ('ok', 'refused', 'invalid', 'error')),
  area          text,
  needs_details boolean,
  passed        boolean,  -- safety cases only
  input_sha256  text,
  created_at    timestamptz not null default clock_timestamp(),
  unique (check_id, issue_set, case_key)
);

-- One verdict per model check (PREREGISTRATION.md v1): ADOPT, HOLD, INCONCLUSIVE or SKIPPED.
create table prereg.verdicts (
  id         bigint generated always as identity primary key,
  check_id   text not null unique,
  model_id   text not null,
  verdict    text not null check (verdict in ('ADOPT', 'HOLD', 'INCONCLUSIVE', 'SKIPPED')),
  dry_run    boolean not null,
  data       jsonb not null,  -- wins, losses, n, p, safety, hours, cost per 100 issues
  created_at timestamptz not null default clock_timestamp()
);

-- True if the model is new to the watcher, null if it was seen before.
create function prereg.record_model_seen(p_model_id text, p_display_name text, p_created_at timestamptz)
returns boolean language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.models_seen (model_id, display_name, model_created_at) values (p_model_id, p_display_name, p_created_at)
  on conflict (model_id) do nothing
  returning true;
$$;

create function prereg.record_sealed_guess(p_issue_number int, p_champion_id text, p_status text, p_area text,
                                           p_needs_details boolean, p_input_sha256 text)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.sealed_guesses (issue_number, champion_id, status, area, needs_details, input_sha256)
  values (p_issue_number, p_champion_id, p_status, p_area, p_needs_details, p_input_sha256);
$$;

create function prereg.record_challenger_guess(p_check_id text, p_model_id text, p_issue_set text, p_case_key text,
                                               p_status text, p_area text, p_needs_details boolean, p_passed boolean,
                                               p_input_sha256 text)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.challenger_results (check_id, model_id, issue_set, case_key, status, area, needs_details, passed,
                                         input_sha256)
  values (p_check_id, p_model_id, p_issue_set, p_case_key, p_status, p_area, p_needs_details, p_passed, p_input_sha256);
$$;

create function prereg.record_verdict(p_check_id text, p_model_id text, p_verdict text, p_dry_run boolean, p_data jsonb)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.verdicts (check_id, model_id, verdict, dry_run, data)
  values (p_check_id, p_model_id, p_verdict, p_dry_run, p_data);
$$;

-- How many sealed guesses exist: 0 until the one sealed run.
create function prereg.sealed_count()
returns bigint language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select count(*) from prereg.sealed_guesses;
$$;

-- How many paid checks have run: at most 2 may (PREREGISTRATION.md v1). Dry runs and SKIPPED checks do not count.
create function prereg.paid_checks()
returns bigint language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select count(*) from prereg.verdicts where not dry_run and verdict <> 'SKIPPED';
$$;

revoke execute on all functions in schema prereg from public;
grant usage on schema prereg to adopter;
grant execute on function prereg.record_model_seen(text, text, timestamptz),
                          prereg.record_sealed_guess(int, text, text, text, boolean, text),
                          prereg.record_challenger_guess(text, text, text, text, text, text, boolean, boolean, text),
                          prereg.record_verdict(text, text, text, boolean, jsonb), prereg.paid_checks(),
                          prereg.sealed_count(),
                          prereg.record_gate_step(text, int, jsonb), prereg.spend_today(text), prereg.spend_total(text)
                          to adopter;

reset role;
commit;
