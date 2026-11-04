# ADR-003: the work queue is pgmq, inside the ledger's database

Status: accepted, 2026-11-05.

## Problem

From Day 5, the poll job only finds new issues, and a worker guesses them. Between the two, the work must survive a crash. A message that keeps failing must stop blocking the rest. And no guess may be saved twice or half saved.

## Options

1. **pgmq**, Supabase's message queue inside Postgres. A read hides the message for a visibility timeout, and every message keeps a read count.
2. **A plain table with `SELECT ... FOR UPDATE SKIP LOCKED`.** It is simple, but I would have to rebuild the visibility timeouts, the read counts and the dead letters myself.
3. **A queue outside the database.** It would bring a second system, and a second set of credentials, and its writes would not share a transaction with the ledger.

## Decision

pgmq, in the same database as the ledger. No job touches the queue directly: they call SECURITY DEFINER functions owned by `prereg_owner` (`db/004_functions.sql`).
- `enqueue_issue` saves a first sight, its baseline guess and its message together.
- `claim_next` reads one message and logs the attempt in `prereg.runs`. On a message's 6th read, it moves the message to `triage_dlq` instead.
- `complete` saves the step, the guess and a 'finished' event, and deletes the message, all in one transaction. The message is the key: if it is already gone, a repeated call does nothing. So a guess is saved once, or not at all.
- `record_failure` saves a failed provider call. The message comes back after its timeout.
- `sweep_abandoned` marks an attempt that neither finished nor failed.

## What would change my mind

- pgmq stops working inside SECURITY DEFINER functions on hosted Supabase (Check 11). Then the worker would call `pgmq.read`, `pgmq.send` and `pgmq.delete` itself, with rights on the two queue tables only.
- The queue grows past what a 15-minute tick can drain.
