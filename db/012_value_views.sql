-- 012_value_views.sql: the value views (Build day 5). Run once as `postgres`, then check_roles.sql.
-- observer reads them (default privileges), and the weekly report uses them. The truth they use is the
-- pre-registered rule of rules/ground_truth.toml v1: the first label that maps to an area, added within 14 days
-- by a human who is not the issue's author. A guess counts only if its anchor came before that label.
begin;
set role prereg_owner;

-- The label mapping of rules/ground_truth.toml v1 (60 labels). A new version is a new migration.
create table prereg.label_areas (
  label text primary key,
  area  text not null check (area in ('frontend', 'auth', 'postgres', 'self-hosted', 'documentation', 'other'))
);
insert into prereg.label_areas (label, area) values
  ('GraphQL', 'other'),
  ('a11y', 'frontend'),
  ('admin-mgr', 'other'),
  ('affects_self_hosted', 'self-hosted'),
  ('ai', 'other'),
  ('analytics', 'other'),
  ('api-gw', 'other'),
  ('auth', 'auth'),
  ('auth-helpers', 'auth'),
  ('billing', 'other'),
  ('branching', 'other'),
  ('cli', 'other'),
  ('coolify', 'self-hosted'),
  ('data apis', 'other'),
  ('database', 'postgres'),
  ('design', 'frontend'),
  ('docs-search', 'documentation'),
  ('documentation', 'documentation'),
  ('edge functions', 'other'),
  ('etl', 'other'),
  ('extensions', 'postgres'),
  ('frontend', 'frontend'),
  ('i18n', 'other'),
  ('infra', 'other'),
  ('integrations', 'other'),
  ('javascript', 'other'),
  ('kb', 'documentation'),
  ('mcp', 'other'),
  ('migrations', 'postgres'),
  ('multigres', 'other'),
  ('networking', 'other'),
  ('observability', 'other'),
  ('platform', 'other'),
  ('postgREST', 'other'),
  ('postgres', 'postgres'),
  ('python', 'other'),
  ('react-js', 'other'),
  ('realtime', 'other'),
  ('redwood-js', 'other'),
  ('replication', 'postgres'),
  ('sdk', 'other'),
  ('self-hosted', 'self-hosted'),
  ('storage', 'other'),
  ('studio', 'frontend'),
  ('supabase-admin-agent', 'other'),
  ('supabase-admin-api', 'other'),
  ('supabase-flutter', 'other'),
  ('supabase-js', 'other'),
  ('supabase-py', 'other'),
  ('supabase-react', 'other'),
  ('supabase-swift', 'other'),
  ('supabase.com', 'frontend'),
  ('supavisor', 'postgres'),
  ('swift', 'other'),
  ('ui library', 'frontend'),
  ('v0', 'other'),
  ('vector', 'postgres'),
  ('webhook/pg_net', 'other'),
  ('website', 'frontend'),
  ('wrappers', 'postgres');

-- The owner's timed baseline (tools/timed.py): the median minutes of one triage decision. Empty until timed.
create table prereg.baseline_timing (
  id             int primary key default 1 check (id = 1),
  median_minutes numeric not null check (median_minutes > 0),
  decisions      int not null check (decisions >= 10)
);

-- The truth of each issue the ledger saw, and when its first counting label came.
create view prereg.v_truth as
select s.issue_number, s.gh_created_at, f.area, f.labeled_at as first_label_at
from prereg.issues_seen s
left join lateral (
  select la.area, o.labeled_at from prereg.outcomes o join prereg.label_areas la on la.label = o.label
  where o.issue_number = s.issue_number and o.action = 'add' and o.actor = 'User' and not o.by_author
    and o.labeled_at <= s.gh_created_at + interval '14 days'
  order by o.labeled_at, o.id limit 1) f on true;

-- Each guess that counts: trial 1, with the time of the anchor that covers it.
create view prereg.v_counting_guesses as
select p.id, p.issue_number, case when p.champion_id = 'rules_v0' then 'baseline' else 'champion' end as series,
       p.champion_id, p.area,
       (select min(a.comment_created_at) from prereg.anchors a where a.upto_prediction_id >= p.id) as anchored_at
from prereg.predictions p where p.trial = 1;

-- Agreement per week of issue creation, per series, under the pre-registered rule.
create view prereg.v_agreement_weekly as
select date_trunc('week', t.gh_created_at) as week, g.series,
       count(*) filter (where t.area is not null) as scorable,
       count(*) filter (where t.area is not null and g.anchored_at < t.first_label_at) as counting,
       count(*) filter (where t.area is not null and g.anchored_at < t.first_label_at and g.area = t.area) as matched,
       round(count(*) filter (where t.area is not null and g.anchored_at < t.first_label_at and g.area = t.area)::numeric
             / nullif(count(*) filter (where t.area is not null and g.anchored_at < t.first_label_at), 0), 4) as agreement
from prereg.v_truth t join prereg.v_counting_guesses g using (issue_number)
group by 1, 2;

-- The live job's model cost per guessed issue, per week.
create view prereg.v_cost_per_issue as
select date_trunc('week', s.created_at) as week, round(sum(s.cost_usd), 6) as cost_usd,
       count(distinct s.issue_number) filter (where s.status = 'ok') as issues_guessed,
       round(sum(s.cost_usd) / nullif(count(distinct s.issue_number) filter (where s.status = 'ok'), 0), 6) as usd_per_issue
from prereg.steps s where s.job = 'tick'
group by 1;

-- Work absorbed, per month: modelled, never realised, because no maintainer used a guess.
create view prereg.v_work_absorbed_monthly as
select date_trunc('month', t.gh_created_at) as month,
       count(*) filter (where g.area = t.area and g.anchored_at < t.first_label_at) as matched_guesses,
       count(*) filter (where g.area = t.area and g.anchored_at < t.first_label_at)
         * (select median_minutes from prereg.baseline_timing) as modelled_minutes,  -- null until timed
       0 as realised_minutes,
       'modelled; 0 realised' as note
from prereg.v_truth t join prereg.v_counting_guesses g using (issue_number)
where g.series = 'champion'
group by 1;

reset role;
commit;
