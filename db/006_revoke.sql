-- 006_revoke.sql: the jobs write only through functions now (Day 5). Run once as `postgres`, then run
-- check_roles.sql and tests/test_db_grants.py. After it, no job role can INSERT, UPDATE or DELETE a ledger
-- table directly; triage_agent holds no table right at all, and notary keeps only its SELECT.
begin;
set local createrole_self_grant = '';
set role prereg_owner;

-- The three reads the poll job still needs, now that it reads no table.
create function prereg.newest_first_sight()
returns timestamptz language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select max(gh_created_at) from prereg.issues_seen;
$$;

create function prereg.unanchored_guesses()
returns bigint language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select count(*) from prereg.predictions
  where id > coalesce((select max(upto_prediction_id) from prereg.anchors), 0);
$$;

-- The daily spend of one job, in USD: the cap that runner/worker.py checks before every call.
create function prereg.spend_today(p_job text)
returns numeric language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select coalesce(sum(cost_usd), 0) from prereg.steps
  where job = p_job collate "C" and created_at >= date_trunc('day', now(), 'UTC');
$$;

-- The circuit breaker's probe call, whatever its result, as a step for no issue.
create function prereg.record_probe(p_step jsonb)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  select prereg.save_step('tick', null, p_step);
$$;

-- claim_next now also returns the first sight's content hash, so a retry can tell an edited issue.
drop function prereg.claim_next(int, text);
create function prereg.claim_next(p_vt int, p_run_id text)
returns table (attempt_id bigint, msg_id bigint, issue_number int, champion_id text, read_ct int,
               content_sha256 text)
language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
#variable_conflict use_column
declare
  m record;
  v_issue int;
  v_seen timestamptz;
  v_sha text;
begin
  loop
    select * into m from pgmq.read('triage_events', p_vt, 1);
    if not found then
      return;
    end if;
    v_issue := case when m.message->>'issue_number' ~ '^[0-9]{1,9}$' then (m.message->>'issue_number')::int end;
    select s.first_seen_at, s.content_sha256 into v_seen, v_sha from prereg.issues_seen s where s.issue_number = v_issue;
    if m.read_ct > 5 or v_seen is null or coalesce(m.message->>'champion_id', '') = '' then
      perform pgmq.send('triage_dlq', m.message);
      perform pgmq.delete('triage_events', m.msg_id);
      insert into prereg.run_events (kind, data)
      values ('dead_letter', jsonb_build_object('msg_id', m.msg_id, 'issue_number', m.message->'issue_number',
                                                'read_ct', m.read_ct,
                                                'reason', case when m.read_ct > 5 then 'read 6 times' else 'malformed' end));
      continue;
    end if;
    if v_seen < clock_timestamp() - interval '24 hours' then
      perform pgmq.delete('triage_events', m.msg_id);
      insert into prereg.run_events (kind, data)
      values ('expired', jsonb_build_object('msg_id', m.msg_id, 'issue_number', v_issue, 'read_ct', m.read_ct));
      continue;
    end if;
    insert into prereg.runs (msg_id, issue_number, champion_id, read_ct, run_id)
    values (m.msg_id, v_issue, m.message->>'champion_id', m.read_ct, p_run_id)
    returning prereg.runs.id into attempt_id;
    msg_id := m.msg_id;
    issue_number := v_issue;
    champion_id := m.message->>'champion_id';
    read_ct := m.read_ct;
    content_sha256 := v_sha;
    return next;
    return;
  end loop;
end $$;

-- A provider failure puts the message back with a fresh read count, behind newer work. So only the 24-hour
-- expiry ends the retries after provider errors, and the 6-read limit still catches crashes and failed reads.
create or replace function prereg.record_failure(p_attempt_id bigint, p_step jsonb)
returns void language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
declare
  a prereg.runs;
begin
  if p_attempt_id is null then
    perform prereg.save_step('tick', null, p_step || '{"status": "error"}');
    return;
  end if;
  select * into a from prereg.runs where id = p_attempt_id;
  if not found then
    raise exception 'no attempt %', p_attempt_id using errcode = '22023';
  end if;
  perform prereg.save_step('tick', a.issue_number, p_step || '{"status": "error"}');
  insert into prereg.run_events (kind, data)
  values ('failed', jsonb_build_object('attempt_id', a.id, 'msg_id', a.msg_id, 'issue_number', a.issue_number));
  if pgmq.delete('triage_events', a.msg_id) then  -- the delete's result stops a repeated call from sending twice
    perform pgmq.send('triage_events', jsonb_build_object('issue_number', a.issue_number, 'champion_id', a.champion_id));
  end if;
end $$;

-- complete() now also refuses a guess by any champion but the one queued with the issue (PREREGISTRATION.md:
-- the guess that counts is trial 1 of the champion models.lock named when the issue was first seen).
create or replace function prereg.complete(p_attempt_id bigint, p_outcome text, p_area text, p_needs_details boolean,
                                           p_input_sha256 text, p_step jsonb)
returns text language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
declare
  a prereg.runs;
begin
  -- "C": a parameter takes the caller's collation, which could make two different words compare equal.
  if p_outcome is null or p_outcome collate "C" not in ('guessed', 'refused', 'invalid', 'gone') then
    raise exception 'unknown outcome %', p_outcome using errcode = '22023';
  end if;
  if p_step->>'status' = 'error' then
    raise exception 'a failed call goes to record_failure, not complete' using errcode = '22023';
  end if;
  select * into a from prereg.runs where id = p_attempt_id;
  if not found then
    raise exception 'no attempt %', p_attempt_id using errcode = '22023';
  end if;
  if p_outcome collate "C" = 'guessed' and (p_step->>'champion_id') collate "C" is distinct from a.champion_id then
    raise exception 'the guess must come from the champion queued with the issue' using errcode = '22023';
  end if;
  if not pgmq.delete('triage_events', a.msg_id) then
    return 'already_done';
  end if;
  if p_step is not null then
    perform prereg.save_step('tick', a.issue_number, p_step);  -- 'tick': the live guesses, under the daily cap
  end if;
  if p_outcome collate "C" = 'guessed' then
    insert into prereg.predictions (issue_number, champion_id, area, needs_details, input_sha256)
    values (a.issue_number, a.champion_id, p_area, p_needs_details, p_input_sha256);
  end if;
  insert into prereg.run_events (kind, data)
  values ('finished', jsonb_build_object('attempt_id', a.id, 'msg_id', a.msg_id, 'issue_number', a.issue_number,
                                         'outcome', p_outcome));
  return 'done';
end $$;

-- How many guesses were lost since a time: dead letters and expired messages. The poll fails loudly on any.
create function prereg.losses_since(p_since timestamptz)
returns bigint language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select count(*) from prereg.run_events where kind in ('dead_letter', 'expired') and created_at >= p_since;
$$;

revoke execute on all functions in schema prereg from public;
grant execute on function prereg.claim_next(int, text), prereg.newest_first_sight(), prereg.unanchored_guesses(),
                          prereg.spend_today(text), prereg.record_probe(jsonb), prereg.losses_since(timestamptz)
                          to triage_agent;

-- The cutover: an issue that the old code saw in the last 24 hours, and that has no champion guess and no
-- final step yet, is queued now, so it keeps its retries. The lock waits for a tick of the old code to end.
lock table prereg.issues_seen, prereg.predictions, prereg.steps in share row exclusive mode;
select pgmq.send('triage_events', jsonb_build_object('issue_number', s.issue_number, 'champion_id', 'haiku55-p0'))
from prereg.issues_seen s
where s.first_seen_at > clock_timestamp() - interval '24 hours'
  and not exists (select from prereg.predictions p where p.issue_number = s.issue_number
                  and p.champion_id = 'haiku55-p0' and p.trial = 1)
  and not exists (select from prereg.steps t where t.issue_number = s.issue_number
                  and t.champion_id = 'haiku55-p0' and t.status in ('refused', 'invalid', 'skipped'));

-- The revoke: the Day 0 and Day 2 table rights of the poll and anchor jobs end here.
revoke all on all tables in schema prereg from triage_agent, notary;
grant select on prereg.predictions, prereg.anchors to notary;  -- the anchor job hashes the rows it reads

reset role;
commit;
