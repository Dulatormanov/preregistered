# Decisions

Newest first. Each entry says what was decided and why.

## 2026-11-04 (Day 0)

- **CREATE ROLE must not give postgres rights.** On Postgres 16+, a role that a non-superuser creates is granted back to its creator, with INHERIT and SET if `createrole_self_grant` asks for them. `001_ledger.sql` sets that to empty for its own transaction. On a local Postgres 17 set to `set, inherit`, leaving the line out let postgres use triage_agent's rights without SET ROLE, and `db/check_roles.sql` caught it.
- **Session pooler, not the direct host.** Free projects reach the direct host over IPv6 only, and GitHub's runners have no IPv6. triage_agent logged in through the session pooler (port 5432, user `triage_agent.<ref>`) on the first try, from the laptop and from a runner. Check 2 result: passed.
- **Owner role.** The schema `prereg` belongs to `prereg_owner`, which cannot log in. `postgres` is a member with INHERIT FALSE, SET TRUE: it gets none of the owner's rights by default and must `SET ROLE prereg_owner` on purpose. Check 1 result: passed on Supabase (Postgres 17.11); all six rows of `db/check_roles.sql` are true.
- **One writer.** `tick.yml` runs in one concurrency group, so only one tick writes at a time, and guesses get their ids in one order. The hash chain depends on this.
- **Anchor only when there is something new.** GitHub stops all new comments on an issue after 2,500. One comment per tick would reach that around Nov 30; at about 4 a day it takes over a year.
- **A lost record heals from GitHub.** The anchor job posts first and records second. If the record is lost (a lost response, a dropped connection), the next run finds that comment on the Notary log and records it before it posts a new one. So every bot comment chains from the one before it, and the log never forks or repeats. Found by the Day 0 review.
- **One cron line per slot.** With four lines, `github.event.schedule` tells each run which slot it was planned for. A run that starts 20 minutes late is then not mistaken for the next slot, which Check 3 needs.
- **Canonical format v1** lives in `notary/canonical.py` and is frozen by `tests/test_canonical.py`. A change means v2, never an edit.
- **No plain-text passwords in SQL.** `scripts/role_password.py` sends only a SCRAM verifier, so the SQL editor's history and the database logs never hold a usable password.
- **The ledger starts at Nov 3, 00:00 UTC.** Day 0 began early on Nov 4 in Almaty, when it was still Nov 3 in UTC. So the first tick also guessed the issues created on Nov 3, and the whole path could be tested on Day 0. These guesses fall outside every scoring window.
- **The database is in us-east-1**, close to GitHub's runners.
