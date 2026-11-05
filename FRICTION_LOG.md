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
