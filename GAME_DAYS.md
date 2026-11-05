Independent project, not affiliated with Supabase.

# Game days

Each game day breaks one thing on purpose, on the live system, and writes down what happened.

| Date | Fault | What should happen | What happened |
|---|---|---|---|
| Nov 5 | Rollback drill: a harmless champion change (`haiku55-p2` as `haiku55-p2-drill`, the same setup), then a revert of `models.lock` by pull request | the first guess on the old champion within about 45 minutes | The rollback took 5 min 23 s from the decision to the first tick on the old champion: revert pull request opened 11:13:40 UTC, gate passed 11:16:08, merged 11:16:28, and the backup clock's tick at 11:19:03 ran `haiku55-p2`. 0 lost, 0 dead letters, and no message queued under the drill's id. No upstream issue came while the drill champion was live (08:03 to 11:16), so it made 0 live guesses. The first `haiku55-p2` guess waits for the next upstream issue: pending. Before it started, the drill found three problems (DECISIONS.md), and GitHub's schedule ran no tick from 07:57 to 09:40, which led to the backup clock. |
| Nov 19 | GD1: kill -9 the worker after the model call and before `complete()` | 0 half-written guesses and 0 duplicates; messages come back after the timeout; every issue is guessed on the next tick; "abandoned" events | pending (the same fault runs in CI on every push: `tests/test_rollback.py`) |
| Nov 21 | GD3: an invalid read token for 90 minutes, and the silent-success variant | GitHub's failed-run email first; Healthchecks after period plus grace; one watchdog issue; the backlog drains after the fix | pending |
| Nov 25 | GD2: the model provider unreachable for 60 minutes | the circuit breaker stops claims; the watchdog opens an issue; 0 lost and 0 dead letters | pending (a fake 3-hour outage runs in CI: `tests/test_outage.py`) |
| Dec 9 | GD4: a lenient judge prompt | the judge drops to advisory; the code checks still decide | pending |
