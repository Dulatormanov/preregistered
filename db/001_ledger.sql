-- 001_ledger.sql: the insert-only ledger.
-- Run once as `postgres` in the Supabase SQL editor, then run check_roles.sql.
begin;

-- Postgres 16+: CREATE ROLE grants each new role back to postgres. Empty keeps
-- that grant ADMIN-only, whatever the server default is, so postgres gets no rights by surprise.
set local createrole_self_grant = '';

-- Check 1: a NOLOGIN owner. postgres may SET ROLE to it on purpose,
-- but does not get its rights by default.
create role prereg_owner nologin;
grant prereg_owner to postgres with inherit false, set true;
create schema prereg authorization prereg_owner;

set role prereg_owner;

-- One row per upstream issue, at first sight. Hashes only, never text.
create table prereg.issues_seen (
  issue_number   int primary key,
  gh_created_at  timestamptz not null,
  content_sha256 text not null,          -- notary/canonical.py content_sha256(title, body)
  labels_at_seen text[] not null,        -- labels the issue already had when first polled
  first_seen_at  timestamptz not null default clock_timestamp()
);

-- The guesses. The database sets id and created_at; no job can choose them.
create table prereg.predictions (
  id            bigint generated always as identity primary key,
  issue_number  int not null references prereg.issues_seen,
  champion_id   text not null,           -- rules_v0, or the model named in models.lock
  trial         smallint not null default 1,
  area          text not null,           -- one label from the taxonomy
  needs_details boolean not null,
  input_sha256  text not null,           -- hash of the exact text the guesser saw
  created_at    timestamptz not null default clock_timestamp(),
  unique (issue_number, champion_id, trial)
);

-- One row per Notary log comment. GitHub's comment time is the proof.
create table prereg.anchors (
  id                 bigint generated always as identity primary key,
  text               text not null,      -- the anchored line, see notary/canonical.py
  chain_hash         text not null unique,
  upto_prediction_id bigint,             -- last guess covered (kind=rows anchors)
  comment_id         bigint not null unique,
  comment_created_at timestamptz not null,
  created_at         timestamptz not null default clock_timestamp()
);

-- What happened, as small JSON events: counts, statuses and times.
create table prereg.run_events (
  id         bigint generated always as identity primary key,
  kind       text not null,
  data       jsonb not null,
  created_at timestamptz not null default clock_timestamp()
);

reset role;

-- Day 0 login role: it can add rows, never change them, and never set id or created_at.
-- note: temporary; 003_roles.sql takes it over on Day 2.
create role triage_agent login;  -- password: scripts/role_password.py, never typed into SQL

set role prereg_owner;
grant usage on schema prereg to triage_agent;
grant select on all tables in schema prereg to triage_agent;
grant insert (issue_number, gh_created_at, content_sha256, labels_at_seen) on prereg.issues_seen to triage_agent;
grant insert (issue_number, champion_id, trial, area, needs_details, input_sha256) on prereg.predictions to triage_agent;
grant insert (text, chain_hash, upto_prediction_id, comment_id, comment_created_at) on prereg.anchors to triage_agent;
grant insert (kind, data) on prereg.run_events to triage_agent;
reset role;

commit;
