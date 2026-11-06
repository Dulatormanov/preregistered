-- 017_deviation_1.sql: deviation 1 from PREREGISTRATION.md v1 (DEVIATIONS.md, 2026-11-06), written before the new
-- window opens and before any live or sealed result exists. Run once as `postgres`, then run check_roles.sql.
-- 1. A label counts if it was added within 7 days of the issue's creation (rules/ground_truth.toml v2; v1 had 14
--    days, and listed 7 as one of its switches).
-- 2. The live window is issues created from 2026-11-07 to 2026-11-13 (v1: 2026-11-14 to 2026-12-04), so the demotion
--    rule reads only those.
begin;
set role prereg_owner;

create or replace view prereg.v_truth as
select s.issue_number, s.gh_created_at, f.area, f.labeled_at as first_label_at
from prereg.issues_seen s
left join lateral (
  select la.area, o.labeled_at from prereg.outcomes o join prereg.label_areas la on la.label = o.label
  where o.issue_number = s.issue_number and o.action = 'add' and o.actor = 'User' and not o.by_author
    and o.labeled_at <= s.gh_created_at + interval '7 days'
  order by o.labeled_at, o.id limit 1) f on true;

create or replace function prereg.area_live_counts()
returns table (area text, guessed bigint, correct bigint) language sql stable security definer
set search_path = pg_catalog, pg_temp as $$
  select g.area, count(*), count(*) filter (where g.area = t.area)
  from prereg.v_counting_guesses g join prereg.v_truth t on t.issue_number = g.issue_number
  where g.series = 'champion' and t.area is not null and g.anchored_at < t.first_label_at
    and t.gh_created_at >= timestamptz '2026-11-07 00:00+00' and t.gh_created_at < timestamptz '2026-11-14 00:00+00'
  group by g.area;
$$;

reset role;
commit;
