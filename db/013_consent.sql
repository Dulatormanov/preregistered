-- 013_consent.sql: the one governed write (Build day 6). Run once as `postgres`, then give proposer and gateway_svc
-- passwords with scripts/role_password.py, then run check_roles.sql. The plan job of promote.yml logs in as
-- proposer; its apply job, the only job with the sandbox write token, logs in as gateway_svc.
begin;
set local createrole_self_grant = '';  -- as in 001: CREATE ROLE gives postgres no rights by surprise

create role proposer login;  -- saves one bundle a day, with its exact bytes and their hash; one model call
alter role proposer noinherit connection limit 2;
alter role proposer set statement_timeout = '30s';
alter role proposer set idle_in_transaction_session_timeout = '30s';
create role gateway_svc login;  -- reads a bundle, claims its approval once, logs every step
alter role gateway_svc noinherit connection limit 2;
alter role gateway_svc set statement_timeout = '30s';
alter role gateway_svc set idle_in_transaction_session_timeout = '30s';

set role prereg_owner;

-- One bundle a day: what the plan job proposes, the exact payload the gateway may send, and its SHA-256.
create table prereg.consent (
  id             bigint generated always as identity primary key,
  day            date not null unique,  -- one bundle per UTC day
  bundle         jsonb not null,        -- the proposal: the issue, the label, and why
  payload        text not null,         -- the exact bytes, as canonical JSON
  payload_sha256 text not null,
  created_at     timestamptz not null default clock_timestamp(),
  unique (id, payload_sha256)
);

-- An approval, used once. The primary key makes a second claim of the same bundle fail (23505), and the foreign
-- key makes a claim with any other hash fail (23503).
create table prereg.consent_claims (
  consent_id      bigint primary key,
  payload_sha256  text not null,
  run_id          text not null,  -- the Actions run whose approval was used
  approver        text not null,
  approval_sha256 text not null,  -- the SHA-256 of the approval comment, which quotes the payload hash
  created_at      timestamptz not null default clock_timestamp(),
  foreign key (consent_id, payload_sha256) references prereg.consent (id, payload_sha256)
);

-- Every step of the gateway: a refusal and its reason, a request sent, what came back, and the read-back.
create table prereg.writes (
  id         bigint generated always as identity primary key,
  consent_id bigint references prereg.consent,
  step       text not null check (step in ('refused', 'sent', 'landed', 'failed', 'read_back')),
  route      text,
  status     int,
  request_id text,
  reason     text,
  created_at timestamptz not null default clock_timestamp()
);

-- The kill switch: the newest row says whether the gateway may write. With no row at all, it may not.
create table prereg.switches (
  id         bigint generated always as identity primary key,
  enabled    boolean not null,
  reason     text not null,
  created_at timestamptz not null default clock_timestamp()
);

-- What each live probe asked for, and what it got, with GitHub's request id.
create table prereg.probe_results (
  id         bigint generated always as identity primary key,
  run_id     text not null,
  probe      text not null,
  want       text not null check (want in ('LANDED', 'REFUSED', 'DENIED')),
  got        text not null check (got in ('LANDED', 'REFUSED', 'DENIED', 'ERROR')),
  status     int,
  request_id text,
  created_at timestamptz not null default clock_timestamp()
);

-- The plan job saves the day's bundle. The database checks the hash of the payload itself.
create function prereg.propose_bundle(p_bundle jsonb, p_payload text, p_payload_sha256 text)
returns bigint language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
declare
  v_id bigint;
begin
  if encode(sha256(convert_to(p_payload, 'UTF8')), 'hex') <> p_payload_sha256 collate "C" then
    raise exception 'the payload does not have this hash' using errcode = '22023';
  end if;
  insert into prereg.consent (day, bundle, payload, payload_sha256)
  values ((clock_timestamp() at time zone 'UTC')::date, p_bundle, p_payload, p_payload_sha256)
  returning id into v_id;
  return v_id;
end $$;

-- The gateway reads the bundle it was started for.
create function prereg.get_bundle(p_consent_id bigint, out bundle jsonb, out payload text, out payload_sha256 text)
language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select c.bundle, c.payload, c.payload_sha256 from prereg.consent c where c.id = p_consent_id;
$$;

-- Defended: one approval, used once, for exactly the bytes it quoted.
create function prereg.claim_consent(p_consent_id bigint, p_payload_sha256 text, p_run_id text, p_approver text,
                                     p_approval_sha256 text)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.consent_claims (consent_id, payload_sha256, run_id, approver, approval_sha256)
  values (p_consent_id, p_payload_sha256, p_run_id, p_approver, p_approval_sha256);
$$;

-- Defended: every gateway step goes in writes. A request may be logged as sent only after its approval was claimed.
create function prereg.record_write(p_consent_id bigint, p_step text, p_route text, p_status int, p_request_id text,
                                    p_reason text)
returns void language plpgsql security definer set search_path = pg_catalog, pg_temp as $$
begin
  if p_step collate "C" in ('sent', 'landed', 'failed', 'read_back')
     and not exists (select from prereg.consent_claims k where k.consent_id = p_consent_id) then
    raise exception 'no claimed approval for bundle %', p_consent_id using errcode = '22023';
  end if;
  insert into prereg.writes (consent_id, step, route, status, request_id, reason)
  values (p_consent_id, p_step, p_route, p_status, p_request_id, p_reason);
end $$;

-- True only if the newest switch row is on.
create function prereg.switch_enabled()
returns boolean language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select coalesce((select s.enabled from prereg.switches s order by s.id desc limit 1), false);
$$;

-- The owner turns the gateway on or off, as prereg_owner. No job may call this.
create function prereg.set_switch(p_enabled boolean, p_reason text)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.switches (enabled, reason) values (p_enabled, p_reason);
$$;

create function prereg.record_probe_result(p_run_id text, p_probe text, p_want text, p_got text, p_status int,
                                           p_request_id text)
returns void language sql security definer set search_path = pg_catalog, pg_temp as $$
  insert into prereg.probe_results (run_id, probe, want, got, status, request_id)
  values (p_run_id, p_probe, p_want, p_got, p_status, p_request_id);
$$;

-- Each area's live record in the window, under the pre-registered rule: the demotion rule reads it.
create function prereg.area_live_counts()
returns table (area text, guessed bigint, correct bigint) language sql stable security definer
set search_path = pg_catalog, pg_temp as $$
  select g.area, count(*), count(*) filter (where g.area = t.area)
  from prereg.v_counting_guesses g join prereg.v_truth t on t.issue_number = g.issue_number
  where g.series = 'champion' and t.area is not null and g.anchored_at < t.first_label_at
    and t.gh_created_at >= timestamptz '2026-11-14 00:00+00'
  group by g.area;
$$;

revoke execute on all functions in schema prereg from public;
grant usage on schema prereg to proposer, gateway_svc;
grant execute on function prereg.propose_bundle(jsonb, text, text), prereg.switch_enabled(), prereg.area_live_counts(),
                          prereg.record_gate_step(text, int, jsonb), prereg.spend_today(text) to proposer;
grant execute on function prereg.get_bundle(bigint), prereg.claim_consent(bigint, text, text, text, text),
                          prereg.record_write(bigint, text, text, int, text, text), prereg.switch_enabled(),
                          prereg.record_probe_result(text, text, text, text, int, text) to gateway_svc;

reset role;
commit;
