-- 011_watcher_reads.sql: what the model watcher reads (Build day 4). Run once as `postgres`, then check_roles.sql.
-- adopter has no table right, so it reads through these functions only.
begin;
set role prereg_owner;

-- The champion's sealed guesses, to compare a challenger with: the issue and the area, nothing else.
create function prereg.sealed_answers()
returns table (issue_number int, area text) language sql stable security definer
set search_path = pg_catalog, pg_temp as $$
  select g.issue_number, g.area from prereg.sealed_guesses g where g.status = 'ok' order by g.issue_number;
$$;

-- When the watcher first saw a model: the verdict reports the hours since then.
create function prereg.model_first_seen(p_model_id text)
returns timestamptz language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select first_seen_at from prereg.models_seen where model_id = p_model_id collate "C";
$$;

-- How many models the watcher has seen: 0 before its first run, which only records the list.
create function prereg.models_seen_count()
returns bigint language sql stable security definer set search_path = pg_catalog, pg_temp as $$
  select count(*) from prereg.models_seen;
$$;

revoke execute on all functions in schema prereg from public;
grant execute on function prereg.sealed_answers(), prereg.model_first_seen(text), prereg.models_seen_count() to adopter;

reset role;
commit;
