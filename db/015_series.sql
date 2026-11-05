-- 015_series.sql: a drill or ADOPT champion is its own series (PREREGISTRATION.md v1, "Separate series").
-- Before this, every guess not by rules_v0 counted as 'champion'. Run once as `postgres`, then run check_roles.sql.
begin;
set role prereg_owner;

create or replace view prereg.v_counting_guesses as
select p.id, p.issue_number,
       case p.champion_id when 'rules_v0' then 'baseline' when 'haiku55-p2' then 'champion' else p.champion_id end as series,
       p.champion_id, p.area,
       (select min(a.comment_created_at) from prereg.anchors a where a.upto_prediction_id >= p.id) as anchored_at
from prereg.predictions p where p.trial = 1;

reset role;
commit;
