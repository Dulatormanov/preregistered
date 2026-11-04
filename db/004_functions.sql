-- 004_functions.sql: the work queue, and the functions the jobs will call instead of writing tables.
-- Run once as `postgres`, then run check_roles.sql. The jobs move onto these functions on Day 5.
-- Every function is SECURITY DEFINER, owned by prereg_owner, with search_path = pg_catalog, pg_temp, and
-- every name inside it is schema-qualified, so a temporary table cannot stand in for a real one.
begin;
set local createrole_self_grant = '';

-- The queues. pgmq.create makes tables in schema pgmq, so this part runs as postgres.
create extension if not exists pgmq;
select pgmq.create('triage_events');  -- one message per issue the champion must guess
select pgmq.create('triage_dlq');     -- messages read 6 times without finishing (dead letters)
-- The functions below run as prereg_owner, so it gets exactly these rights on the two queues.
grant usage on schema pgmq to prereg_owner;
grant select, insert, update, delete on pgmq.q_triage_events, pgmq.q_triage_dlq to prereg_owner;

set role prereg_owner;

-- One row per attempt: a job took a message from the queue. Whether it finished is an event.
create table prereg.runs (
  id           bigint generated always as identity primary key,
  msg_id       bigint not null,
  issue_number int not null references prereg.issues_seen,
  champion_id  text not null,  -- the champion named in models.lock when the issue was queued
  read_ct      int not null,   -- how many times the message has been read, this read included
  run_id       text,           -- the GitHub Actions run
  created_at   timestamptz not null default clock_timestamp()
);

-- First sight: save the issue, its baseline guess and its queue message together. False if already seen.
create function prereg.enqueue_issue(p_issue_number int, p_gh_created_at timestamptz, p_content_sha256 text,
                                     p_labels text[], p_champion_id text, p_baseline jsonb)
returns boolean language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
begin
  insert into prereg.issues_seen (issue_number, gh_created_at, content_sha256, labels_at_seen)
  values (p_issue_number, p_gh_created_at, p_content_sha256, p_labels) on conflict do nothing;
  if not found then
    return false;
  end if;
  if p_baseline is not null then  -- {"champion_id", "area", "needs_details", "input_sha256"}
    insert into prereg.predictions (issue_number, champion_id, area, needs_details, input_sha256)
    values (p_issue_number, p_baseline->>'champion_id', p_baseline->>'area',
            (p_baseline->>'needs_details')::boolean, p_baseline->>'input_sha256');
  end if;
  perform pgmq.send('triage_events', jsonb_build_object('issue_number', p_issue_number, 'champion_id', p_champion_id));
  return true;
end $$;

-- Take the next message for p_vt seconds and log the attempt. On its 6th read a message is a dead letter:
-- it moves to triage_dlq, and the next message is tried instead.
create function prereg.claim_next(p_vt int, p_run_id text)
returns table (attempt_id bigint, msg_id bigint, issue_number int, champion_id text, read_ct int)
language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
#variable_conflict use_column
declare
  m record;
begin
  loop
    select * into m from pgmq.read('triage_events', p_vt, 1);
    if not found then
      return;
    end if;
    if m.read_ct > 5 then
      perform pgmq.send('triage_dlq', m.message);
      perform pgmq.delete('triage_events', m.msg_id);
      insert into prereg.run_events (kind, data)
      values ('dead_letter', jsonb_build_object('msg_id', m.msg_id, 'issue_number', m.message->'issue_number',
                                                'read_ct', m.read_ct));
      continue;
    end if;
    insert into prereg.runs (msg_id, issue_number, champion_id, read_ct, run_id)
    values (m.msg_id, (m.message->>'issue_number')::int, m.message->>'champion_id', m.read_ct, p_run_id)
    returning prereg.runs.id into attempt_id;
    msg_id := m.msg_id;
    issue_number := (m.message->>'issue_number')::int;
    champion_id := m.message->>'champion_id';
    read_ct := m.read_ct;
    return next;
    return;
  end loop;
end $$;

-- Save one step row from the champion's step dict (agents/champion.py), for the attempt's issue.
create function prereg.save_step(p_job text, p_issue_number int, p_step jsonb)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.steps (job, issue_number, champion_id, model, status, request_id, input_tokens, output_tokens,
                            cache_read_tokens, cache_write_tokens, cost_usd, lock_sha256, error)
  values (p_job, p_issue_number, p_step->>'champion_id', p_step->>'model', p_step->>'status', p_step->>'request_id',
          coalesce((p_step->>'input_tokens')::int, 0), coalesce((p_step->>'output_tokens')::int, 0),
          coalesce((p_step->>'cache_read_tokens')::int, 0), coalesce((p_step->>'cache_write_tokens')::int, 0),
          coalesce((p_step->>'cost_usd')::numeric, 0), p_step->>'lock_sha256', p_step->>'error');
$$;
revoke execute on function prereg.save_step(text, int, jsonb) from public;  -- only other functions call it

-- Finish an attempt, all in one transaction: the step, the guess (outcome 'guessed'), a 'finished' event,
-- and the message's delete. The message is the key: if it is already gone, a repeated call does nothing.
-- Outcomes: guessed, refused, invalid (the model answered), gone (deleted, hidden or moved: no guess).
create function prereg.complete(p_attempt_id bigint, p_outcome text, p_area text, p_needs_details boolean,
                                p_input_sha256 text, p_step jsonb)
returns text language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
declare
  a prereg.runs;
begin
  if p_outcome not in ('guessed', 'refused', 'invalid', 'gone') then
    raise exception 'unknown outcome %', p_outcome using errcode = '22023';
  end if;
  select * into a from prereg.runs where id = p_attempt_id;
  if not found then
    raise exception 'no attempt %', p_attempt_id using errcode = '22023';
  end if;
  if not pgmq.delete('triage_events', a.msg_id) then
    return 'already_done';
  end if;
  if p_step is not null then
    perform prereg.save_step('worker', a.issue_number, p_step);
  end if;
  if p_outcome = 'guessed' then
    insert into prereg.predictions (issue_number, champion_id, area, needs_details, input_sha256)
    values (a.issue_number, p_step->>'champion_id', p_area, p_needs_details, p_input_sha256);
  end if;
  insert into prereg.run_events (kind, data)
  values ('finished', jsonb_build_object('attempt_id', a.id, 'msg_id', a.msg_id, 'issue_number', a.issue_number,
                                         'outcome', p_outcome));
  return 'done';
end $$;

-- A provider call that failed: save its step and a 'failed' event. The message stays in the queue and is
-- read again after its visibility timeout; on its 6th read it becomes a dead letter.
create function prereg.record_failure(p_attempt_id bigint, p_step jsonb)
returns void language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
declare
  a prereg.runs;
begin
  select * into a from prereg.runs where id = p_attempt_id;
  if not found then
    raise exception 'no attempt %', p_attempt_id using errcode = '22023';
  end if;
  perform prereg.save_step('worker', a.issue_number, p_step || '{"status": "error"}');
  insert into prereg.run_events (kind, data)
  values ('failed', jsonb_build_object('attempt_id', a.id, 'msg_id', a.msg_id, 'issue_number', a.issue_number));
end $$;

-- The circuit breaker's input: provider errors saved in the last 60 minutes.
create function prereg.recent_provider_failures()
returns bigint language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select count(*) from prereg.steps where status = 'error' and created_at > now() - interval '60 minutes';
$$;

-- The poll's 'polled' event. Every other kind of event is written by a function above.
create function prereg.log_event(p_kind text, p_data jsonb)
returns void language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
begin
  if p_kind <> 'polled' then
    raise exception 'log_event writes polled events only' using errcode = '42501';
  end if;
  insert into prereg.run_events (kind, data) values (p_kind, p_data);
end $$;

-- An anchor, after its comment is on the Notary log (post first, record second; a lost record heals).
create function prereg.record_anchor(p_text text, p_chain_hash text, p_upto bigint, p_comment_id bigint,
                                     p_comment_created_at timestamptz)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.anchors (text, chain_hash, upto_prediction_id, comment_id, comment_created_at)
  values (p_text, p_chain_hash, p_upto, p_comment_id, p_comment_created_at);
$$;

-- An 'abandoned' event for each attempt that neither finished nor failed within p_min_age, then a
-- 'sweep_ran' event. pg_cron runs it every 10 minutes from Build day 1.
create function prereg.sweep_abandoned(p_min_age interval)
returns int language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
declare
  n int;
begin
  insert into prereg.run_events (kind, data)
  select 'abandoned', jsonb_build_object('attempt_id', r.id, 'msg_id', r.msg_id, 'issue_number', r.issue_number)
  from prereg.runs r
  where r.created_at < clock_timestamp() - p_min_age
    and not exists (select from prereg.run_events e where e.kind in ('finished', 'failed', 'abandoned')
                    and e.data->>'attempt_id' = r.id::text);
  get diagnostics n = row_count;
  insert into prereg.run_events (kind, data) values ('sweep_ran', jsonb_build_object('abandoned', n));
  return n;
end $$;

-- Each function is closed to PUBLIC, then opened to the one job that calls it.
revoke execute on all functions in schema prereg from public;
grant execute on function prereg.enqueue_issue(int, timestamptz, text, text[], text, jsonb),
                          prereg.claim_next(int, text),
                          prereg.complete(bigint, text, text, boolean, text, jsonb),
                          prereg.record_failure(bigint, jsonb),
                          prereg.recent_provider_failures(),
                          prereg.log_event(text, jsonb) to triage_agent;
grant execute on function prereg.record_anchor(text, text, bigint, bigint, timestamptz) to notary;
-- note: sweep_abandoned gets its caller (the pg_cron role) on Build day 1.

reset role;
commit;
