-- 002_steps.sql: one row per champion attempt: a model call with its tokens, cost and the provider's
-- request id, or a final 'skipped' when the issue changed or disappeared before its call.
-- Run once as `postgres`, then run check_roles.sql. Never holds issue text: errors keep class and status only.
begin;
set role prereg_owner;

create table prereg.steps (
  id                 bigint generated always as identity primary key,
  job                text not null,           -- 'tick' (the live guesses, under the daily cap) or 'check4'
  issue_number       int,                     -- null for a call that is not about one issue
  champion_id        text not null,           -- the setup in models.lock that made the call
  model              text not null,
  status             text not null check (status in ('ok', 'refused', 'invalid', 'error', 'skipped')),
  request_id         text,                    -- the provider's request-id, for support tickets
  input_tokens       int not null default 0,
  output_tokens      int not null default 0,
  cache_read_tokens  int not null default 0,
  cache_write_tokens int not null default 0,
  cost_usd           numeric(12, 6) not null default 0,  -- from prices.toml at call time
  lock_sha256        text not null,           -- sha256 of models.lock at call time
  error              text,                    -- error class and HTTP status, or why it was skipped
  created_at         timestamptz not null default clock_timestamp()
);

-- note: triage_agent reads steps for the daily cap; spend_today() replaces that on Build day 1.
grant select on prereg.steps to triage_agent;
grant insert (job, issue_number, champion_id, model, status, request_id, input_tokens, output_tokens,
              cache_read_tokens, cache_write_tokens, cost_usd, lock_sha256, error) on prereg.steps to triage_agent;

reset role;
commit;
