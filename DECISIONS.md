# Decisions

Newest first. Each entry says what was decided and why.

## 2026-11-04 (Day 1, started a day early)

- **The champion is Claude Haiku 5.5** (`haiku55-p0` in `models.lock`): effort low, thinking off, and structured output that can only name one of the six areas. One call per issue costs about $0.0002. `models.lock` pins the prompt and the taxonomy by their SHA-256, and the job stops if they differ.
- **The keyword rule keeps guessing** as the baseline series. It costs nothing, and it is the floor every model must beat on the same issues.
- **A cap of $3 a day, in code.** The Anthropic key has no workspace limit, so the live job checks today's spend in `prereg.steps` before every call. `spend_today()` moves this check into the database on Build day 1.
- **Retries.** A champion call that errors is tried again on later ticks, for 24 hours. The issue is read again from GitHub, because the ledger keeps no issue text. The champion guesses only if the text is unchanged since first sight; an issue that was edited, deleted or hidden gets a final `skipped` step. A refusal or an invalid answer is final too: it is a result. The next tick is the only retry, because the SDK would sleep through a long `retry-after`.
- **Limits per tick:** at most 10 model calls, and no new call after 2 minutes, so a slow API cannot reach the job's 5-minute limit.
- **A failed tick still anchors.** If no call in a tick gets an answer, or the champion step crashes, the poll job records the run and then fails. The anchor job runs anyway, so the saved guesses get their anchor, but it does not ping Healthchecks, so the alarm still fires. Found by the Day 1 review.
- **Waiting runs queue** (`queue: max`). Without it, the next scheduled run would replace a file-anchor run that is waiting behind a tick.
- **`kind=file` anchors** were added to canonical format v1 before the first one. The rules for rows and chains did not change, and the frozen tests still pass.
- **Config files are TOML**, which Python reads with no extra package. Workflow files stay YAML.
- **Installs take wheels only** (`--only-binary :all:`), so installing never runs package code, in the job that holds the issues:write token too.
- **Migration numbers:** `002` is the steps table, so the roles become `003`, the functions `004` and the cron jobs `005`.
- **Check 4 result: passed.** On 20 dev-set issues (created Sep 1-19), all 20 calls answered: no refusal, invalid answer or error. They averaged 1,465 input tokens (the most was 9,156) and 16 output tokens: $0.000155 per issue, or $0.016 per 100 issues. At about 2 new issues a day, the live job costs well under a cent a day, far below the $3 cap.
- **The first Day 1 tick** gave champion guesses to the 3 Day 0 issues whose text was unchanged, and skipped the 1 that had been edited since the job first saw it.

## 2026-11-04 (Day 0)

- **No Google Cloud, no OpenRouter.** Supabase Postgres stays the only store: three Postgres views will give the weekly numbers, and the model watcher will test Anthropic models only. That means one cloud account, one card and two secrets fewer, and one more build day for the clock and the gate.
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
