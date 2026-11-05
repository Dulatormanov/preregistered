# ADR-008: the contact budget

Status: accepted, 2026-11-05.

## Problem

An agent that can post can also nag. Alerts that repeat every 30 minutes, a second weekly report, or a stream of approval requests would teach people to ignore the project, and every message reaches a real inbox. The limit must hold even when two jobs post at the same moment.

## Options

1. **Limits in code** in each job. Two runs at once can both pass the check before either one posts.
2. **The contact budget in Postgres.** Every message spends from `prereg.contacts` first, and the table's unique key is the budget.

## Decision

Option 2 (`db/014_contacts.sql`). `prereg.spend_contact(kind, topic)` inserts one row whose unique key is (kind, topic, window): one weekly report a week, one approval request a day, and one new issue or comment per alert type per 6 hours. A second message in its window fails with 23505, so of 50 sends at once exactly one lands (`tests/test_contacts.py`).

- Every job that posts spends first, through `ops/notify.py`: the alert jobs, the weekly report's post job, and the plan job of `promote.yml` (the approval request).
- The jobs that post log in as `notifier`, which can call `spend_contact` and nothing else, not even read a table.
- An alert over its budget is skipped and logged in the job's output. A second weekly report fails its job.

## What would change my mind

- An alert that matters waits 6 hours behind a duplicate: then alerts get a severity, and severe ones a shorter window.
