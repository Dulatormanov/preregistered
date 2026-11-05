-- 016_review.sql: fixes from the review of Build days 4 to 8. Run once as `postgres`, then run check_roles.sql.
-- 1. The sealed run: an API error is never saved as an issue's one guess, so a later run can guess it. An issue whose
--    text changed gets a 'left_out' row instead, so the run is complete when every sealed issue has its one row.
-- 2. The demotion rule reads only the window's issues, created Nov 14 to Dec 4 (PREREGISTRATION.md v1):
--    area_live_counts had the window's start but no end.
begin;
set role prereg_owner;

alter table prereg.sealed_guesses drop constraint sealed_guesses_status_check,
  add constraint sealed_guesses_status_check check (status in ('ok', 'refused', 'invalid', 'left_out'));

-- The sealed run's rows: the run reads which issues still need their one row, and the model check reads the guesses.
create function prereg.sealed_rows()
returns table (issue_number int, status text, area text) language sql stable security definer
set search_path = pg_catalog, pg_temp as $$
  select g.issue_number, g.status, g.area from prereg.sealed_guesses g order by g.issue_number;
$$;
revoke execute on function prereg.sealed_rows() from public;
grant execute on function prereg.sealed_rows() to adopter;

create or replace function prereg.area_live_counts()
returns table (area text, guessed bigint, correct bigint) language sql stable security definer
set search_path = pg_catalog, pg_temp as $$
  select g.area, count(*), count(*) filter (where g.area = t.area)
  from prereg.v_counting_guesses g join prereg.v_truth t on t.issue_number = g.issue_number
  where g.series = 'champion' and t.area is not null and g.anchored_at < t.first_label_at
    and t.gh_created_at >= timestamptz '2026-11-14 00:00+00' and t.gh_created_at < timestamptz '2026-12-05 00:00+00'
  group by g.area;
$$;

reset role;
commit;
