-- 009_gate_connections.sql: gate_runner may hold 4 sessions (Build day 1 review). Run once as `postgres`.
-- Up to four suite runs can overlap: the gate on two pull requests, suite.yml after a merge, and the Monday control.
-- Each holds one session for its whole run, so a limit of 2 would fail the third at login.
alter role gate_runner connection limit 4;
