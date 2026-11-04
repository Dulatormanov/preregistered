-- 008_cron.sql: the sweeper (Build day 1). Run once as `postgres`, then run check_roles.sql.
-- Every 10 minutes, pg_cron marks each attempt that started over 15 minutes ago and never finished as
-- 'abandoned', and logs a 'sweep_ran' event, which the watchdog's slot rule checks. pg_cron runs a job as the
-- role that scheduled it, so postgres gets EXECUTE on sweep_abandoned, and no other right in prereg.
begin;
create extension if not exists pg_cron;

set role prereg_owner;
grant execute on function prereg.sweep_abandoned(interval) to postgres;
reset role;

select cron.schedule('prereg-sweeper', '*/10 * * * *', $$select prereg.sweep_abandoned('15 minutes')$$);
commit;
