Independent project, not affiliated with Supabase.

# Game days

Each game day breaks one thing on purpose, on the live system, and writes down what happened.

| Date | Fault | What should happen | What happened |
|---|---|---|---|
| Nov 19 | GD1: kill -9 the worker after the model call and before `complete()` | 0 half-written guesses and 0 duplicates; messages come back after the timeout; every issue is guessed on the next tick; "abandoned" events | pending (the same fault runs in CI on every push: `tests/test_rollback.py`) |
| Nov 19 | Rollback drill: revert `models.lock` by pull request | the first guess on the old champion within about 45 minutes | pending |
| Nov 21 | GD3: an invalid read token for 90 minutes, and the silent-success variant | GitHub's failed-run email first; Healthchecks after period plus grace; one watchdog issue; the backlog drains after the fix | pending |
| Nov 25 | GD2: the model provider unreachable for 60 minutes | the circuit breaker stops claims; the watchdog opens an issue; 0 lost and 0 dead letters | pending (a fake 3-hour outage runs in CI: `tests/test_outage.py`) |
| Dec 9 | GD4: a lenient judge prompt | the judge drops to advisory; the code checks still decide | pending |
