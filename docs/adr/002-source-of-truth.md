# ADR-002: Postgres is the only store

Status: accepted, 2026-11-05.

## Problem

The guesses, the label events, the queue, the anchors, the model checks and the weekly numbers all need a home. Each extra store is one more account, one more card, one more set of secrets to keep, and one more place where the numbers could disagree.

## Options

1. **Supabase Postgres only:** the ledger, the queue (pgmq), the scheduler for the sweeper (pg_cron), and the views for the weekly numbers.
2. **A cloud warehouse next to it** (for example BigQuery), fed from Postgres, for the analysis.
3. **Files in the repo** for the results, and Postgres only for the live writes.

## Decision

Option 1. Supabase Postgres is the only store. The value views (`v_agreement_weekly`, `v_cost_per_issue`, `v_work_absorbed_monthly`, in `db/012_value_views.sql`) give the weekly numbers in SQL, next to the data they count, and `observer` reads them. The repo holds only what must be public and versioned: the code, the rules, the anchored files, and results that are counts only.

A warehouse was planned, and dropped on Day 0 (DECISIONS.md, 2026-11-04): it would have meant a second cloud account, a card and two more secrets, for data that fits easily in one free Postgres. The time went into the clock and the gate instead.

## What would change my mind

- The views get too slow for the weekly report on the free plan.
- Someone else needs to run their own analysis on the data: then the daily reveal to the `data` branch (Build day 8) is the public copy, not a warehouse.
