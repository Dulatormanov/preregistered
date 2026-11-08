# Friction log

What was harder than it should be, and what it cost.

## 2026-11-04 (Day 0)

- A page of 100 upstream issues is about 0.5 MB, and on the laptop's connection one download was cut off. Pages are now 30 issues.
- The laptop's `gh` token cannot change notification settings (`updateSubscription` needs the `notifications` scope), so unsubscribing from the Notary log was one click in the browser instead.
- The first tick posted its anchor, then failed at the Healthchecks ping: `curl: (3) URL rejected: Malformed input to a URL function`. The pasted `HC_TICK_URL` secret most likely ended with a copied newline. Saving it again with `printf '%s' URL | gh secret set` and re-running the failed job fixed it, in about 3 minutes.
- The schedule never started. The workflow was disabled when `tick.yml` was pushed, and enabling it at 10:56 UTC did not register the cron lines: no scheduled run came in the next 4.5 hours. Pushing a change to `tick.yml` at about 15:35 UTC was the fix to try. The ledger has no ticks between 10:57 and then.
- GitHub opened an incident at 16:05 UTC ("Incident with Actions and Pages", Actions partial outage). By then the schedule had still never fired; runs started by hand kept working.
- After every push that changed `tick.yml` (15:30, 16:22 and 19:05 UTC on Nov 4), GitHub's scheduler skipped the next hour or more of slots. From now on, the logic lives in Python files and `tick.yml` stays as it is.

## 2026-11-04 (Days 5 to 7, built the same evening)

- After the 19:05 UTC push (Day 2, the last change to `tick.yml`), GitHub ran no scheduled tick for hours: none from 18:53 UTC until 00:15 UTC on Nov 5, a gap of 5 hours 22 minutes. GitHub's status page showed no open incident. A tick started by hand worked. Hand-started ticks do not stand in for the schedule: the weekly report counts them apart, as tick runs that fill no slot.
- The plan's package name `platform/` would clash with Python's own `platform` module, which the Anthropic SDK imports. Build day 1 uses `core/` instead.
- `drift.yml` did not parse: a `": "` inside an unquoted `${{ }}` default is not valid YAML. GitHub showed the workflow under its file path and refused to start it. Nothing had checked the YAML, because the registry test reads the workflow files with its own small reader. CI now parses every workflow file with Ruby's YAML parser, which the runners already have.
- The scheduler came back for 18 minutes only: scheduled ticks ran at 00:15, 00:25, 00:29 and 00:33 UTC on Nov 5, then none again until 07:17 UTC. In that time I merged about 15 pull requests, and most of them changed a workflow file. The pattern from Days 0 to 2 holds for any workflow file, not only `tick.yml`. So from Build day 8 on, workflow changes go out in as few merges as possible.

## 2026-11-05 (from 07:17 UTC)

- The secret `HC_WATCHDOG_URL` was saved only at 09:39 UTC, so until then nothing would have noticed a stopped watchdog. The watchdog's own issue had said so since 23:21 UTC on Nov 4.
- GitHub's schedule started no tick from 07:57 to 09:40 UTC, so ticks were started by hand at 09:40 and 09:54, and the watchdog at 09:40. From 10:04 the backup clock on the owner's server did that (ADR-001), with a token the owner made for it.
- Up to 11:00 UTC, GitHub's schedule started 2 of 22 watchdog runs and 1 of 11 model-watcher runs, so the watchdog opened `missed:watch/watch`. The backup clock took both over the same day.
- From 15:34 UTC to 07:15 UTC on Nov 6 (15 h 41 min) the backup clock started nothing: a hand edit of its server copy, made for GD3, did not compile, and the read token GD3 had broken stayed broken. Fixed by hand at 07:15: the server copy copied again from `ops/backup_clock.py`, the token saved again, and a tick started. The server copy is now only ever copied and compiled, never edited (DECISIONS.md, Nov 6).

## 2026-11-06

- By 07:18 UTC, GitHub's schedule had started none of the day's reveal, drift check and outcome collector (the drift check had run 8 hours late on Nov 5), so all three were started by hand. The backup clock has started them since.
- GD3's second try broke the read token at 08:40 UTC from a script on the owner's laptop, and the laptop slept, so the script never put it back: two ticks failed loudly until the token was saved again by hand at 09:02. A timed game-day step now runs on the owner's server.
- GitHub never shows a saved secret again, so putting the read token back after GD3 needed a spare made before it. That spare, `prereg-read-2`, is now the live token, and the unused `prereg-read` has to be deleted by hand in GitHub's settings.
- At 13:19 UTC the watchdog opened `missed:tick/poll`, although every tick had read upstream with HTTP 200: GitHub's schedule had started three ticks 48 to 51 minutes late, and the watchdog counted each for its planned slot (DECISIONS.md, Nov 6). The issue was closed by hand at 14:20, after the fixed watchdog's first run.

## 2026-11-08

- The sealed score's pull request failed `test` twice, both times on a test, not on the score. `tests/test_weekly_report.py` created an issue at `now()`, which since Nov 7 falls in the live window, and `tests/test_enforcement.py` used `frontend` as its label that was not promoted, and the sealed score promoted it. Two test-only pull requests fixed them, and the score was merged at 09:21 UTC. A pull request opened by `GITHUB_TOKEN` starts no checks, so each try needed the pull request closed and reopened by hand.
