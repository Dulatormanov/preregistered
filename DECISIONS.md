# Decisions

Newest first. Each entry says what was decided and why.

## 2026-11-05 (Day 4)

- **The golden set** (`golden/build.py`): 688 issues created May 1 to Oct 31. It keeps their numbers, content hashes, close reasons and label events, with each actor's type and whether the actor was the issue's author. It never keeps issue text or a login. The label events stay in a git-ignored file, because their times would show how fast the maintainers work.
- **The sealed set is fixed:** 151 issues created Sep 20 to Oct 31. `golden/v1/sealed_list.csv` holds their numbers and content hashes, and no labels. `golden/v1/SEALED.sha256` holds that list's hash, `5ce27096ce15ff3c253e803e5f74173ba92123c61ad44089fd1a52d495d179ab`. It is anchored on the Notary log before any tuning.
- **Ground truth** (ADR-006): the first counting label, within 14 days, added by a human who is not the author. Every one of Supabase's 121 labels is either mapped to an area or ignored.
- **Check 12 result:** only frontend has at least 15 scorable sealed issues. The other five areas cannot reach the promotion bar. The bar stays as it is, and the plan's fallback (synthetic sandbox issues) covers the governed write.
- **The reference lint** (`scripts/lint_refs.py`) blocks cross-repo references, issue URLs, bare `#N` and @mentions, and allows this repo's own URLs. The anchor job lints every text before it posts.
- **Outcomes:** `db/005_outcomes.sql` adds the collector role and `prereg.outcomes`, which is written only through `record_outcome()`. Each GitHub event is saved once, because its id's hash is unique. `outcomes.yml` runs daily, and opens one alert issue for an unknown label.
- **Migration numbers:** `005` is now the outcomes, so the cron jobs become `006`.
- **Check 3, first result:** in the one hour that ran normally (the 18:00 UTC slots on Nov 4), ticks started 1 to 26 minutes after their slot, 16 minutes at the median. After each push that changed `tick.yml`, GitHub ran no scheduled tick for an hour or more. So `tick.yml` changes as rarely as possible. Check 3 is measured again on Day 7, with more days of data.

## 2026-11-05 (Day 3)

- **The queue is pgmq** (ADR-003): `triage_events` and `triage_dlq`, in the ledger's database. No job touches it directly. The jobs call SECURITY DEFINER functions owned by `prereg_owner`, with `search_path = pg_catalog, pg_temp` and every name schema-qualified. Each function is closed to PUBLIC and opened to the one job that calls it (check 11).
- **Changes from the plan's list of functions:**
  - `claim_next` also logs the attempt, so there is no separate `log_attempt`.
  - `record_failure` takes the attempt and the step, instead of (msg_id, http_status, request_id).
  - `record_anchor` only inserts: the anchor job posts first and records second, so it reads the rows to hash itself, as notary.
  - `enqueue_issue` also saves the baseline guess, which the plan did not have.
- **`complete` is idempotent by design.** It deletes the queue message first, and if the message is already gone, it does nothing. So a guess is saved once or not at all, even if two workers finish the same message.
- **Supabase lets postgres read the ledger.** On hosted Supabase and in its image, postgres is a member of `pg_read_all_data`. It can read every table, but it still changes nothing without `SET ROLE prereg_owner`. The privilege matrix in `credentials.toml` says so, and the test checks it.
- **A test database on Supabase's own image** (Check 10). `tests/setup_test_db.py` builds it from every migration, and CI does the same on each push, with `supabase/postgres:17.11.0.018` pinned by digest. Three suites run there:
  - `tests/test_db_functions.py`: 7 tests, including the poison message on its 6th read and the temp-table hijack;
  - `tests/test_privilege_matrix.py`: the live privileges must equal `credentials.toml`, and `tests/fixtures/bad_grant.sql` must be caught;
  - the grant test: 220 attempts.
- **Check 10 result:** pending. **Check 11 result:** pending.

## 2026-11-05 (Day 2)

- **One login per job.** `triage_agent` (the poll job) adds first sights, guesses, steps and run events. `notary` (the anchor job) adds anchors only. `observer` reads everything and adds nothing. So the poll job can no longer write an anchor record, and the anchor job can no longer write a guess.
- **Job roles are NOINHERIT, with at most 2 connections and 30-second statement and idle timeouts.** NOINHERIT does not stop SET ROLE, so check 9 keeps every job role a member of no role. The timeouts are session defaults: they stop a buggy job, not a leaked login. Check 8 alerts if they change.
- **Autocommit.** Neither job keeps a transaction open over the network. Writes that belong together share one short transaction. A tick's first sights are all or nothing, because the next cutoff comes from the newest one.
- **Two layers of checks.** `db/check_roles.sql` reads the catalog: 9 checks, for every role and every kind of right (column UPDATE, TRIGGER, views, column SELECT). `tests/test_db_grants.py` tries 187 forbidden actions as each job role. Each attempt touches zero rows, so even one that is wrongly allowed changes nothing and uses no id. The Day 2 review found 6 gaps in the first version, and each one now turns a check red.
- **`credentials.toml`** lists every secret, with what it can do, what it must never do, and when it expires.
- **Check 9 result: passed.** GitHub sends the read token's expiry header, and the poll job saves it in each 'polled' event: `prereg-read` expires on 2027-02-01 19:00 UTC.
- **The grant test passed on prereg-prod:** all 187 forbidden attempts were denied with 42501, and all 9 catalog checks are true.
- **The schedule started** at 18:32 UTC, after GitHub's incident ended. Before that, no scheduled run came at all.

## 2026-11-04 (Day 1, started a day early)

- **PREREGISTRATION.md v0 is anchored**: anchor 3 on the Notary log, at 16:31:59 UTC, pins it at commit 4567c8b. A second run 40 seconds later pinned the same file at the same commit again (anchor 4). The first time counts. Both comments recompute.
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
