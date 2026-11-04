# ADR-001: the runtime is GitHub Actions

Status: accepted, 2026-11-04.

## Problem

Every 15 minutes, one job must read new public issues, make the guesses, save them, and post a hash on GitHub. It must run without a laptop, keep a public record of every run, and never run twice at the same time, because the hash chain needs one writer.

## Options

1. **GitHub Actions on a schedule.** It is free for a public repo. Every run has a public log, and a `concurrency` group gives one writer.
2. **Supabase pg_cron with an Edge Function.** It stays close to the data, but its runs leave no public log.
3. **cron on a small server of my own.** I would control it fully, but it costs money, and nobody outside can see its runs.

## Decision

GitHub Actions. The repo is the public record, so its runs are part of the proof.

## GitHub's Actions terms

The terms say Actions is for developing and testing your own applications, and they warn against using it as part of a serverless application. These runs are this repo's own software, run and tested in the open. Each tick takes about a minute, and the weekly report shows Actions minutes per day.

## What would change my mind

- GitHub warns about this use. Then the tick moves to cron on a small server that same day.
- Scheduled runs come hours apart. Then the alarm grace comes from the measured delays (Check 3), and the README reports them.
