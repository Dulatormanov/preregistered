Independent project, not affiliated with Supabase.

# Game days

Each game day breaks one thing on purpose, on the live system, and writes down what happened.

| Date | Fault | What should happen | What happened |
|---|---|---|---|
| Nov 5 | Rollback drill: a harmless champion change (`haiku55-p2` as `haiku55-p2-drill`, the same setup), then a revert of `models.lock` by pull request | the first guess on the old champion within about 45 minutes | The rollback took 5 min 23 s from the decision to the first tick on the old champion: revert pull request opened 11:13:40 UTC, gate passed 11:16:08, merged 11:16:28, and the backup clock's tick at 11:19:03 ran `haiku55-p2`. 0 lost, 0 dead letters, and no message queued under the drill's id. No upstream issue came while the drill champion was live (08:03 to 11:16), so it made 0 live guesses. The next upstream issue came at 11:34, and the backup clock's tick guessed it with `haiku55-p2` at 11:34:23 (anchored at 11:34:40): the first guess on the old champion came 20 min 44 s after the decision, within the 45 minutes. Before it started, the drill found three problems (DECISIONS.md), and GitHub's schedule ran no tick from 07:57 to 09:40, which led to the backup clock. |
| Nov 19 | GD1: kill -9 the worker after the model call and before `complete()` | 0 half-written guesses and 0 duplicates; messages come back after the timeout; every issue is guessed on the next tick; "abandoned" events | pending (the same fault runs in CI on every push: `tests/test_rollback.py`) |
| Nov 5 | GD3: an invalid read token for 90 minutes, and the silent-success variant | GitHub's failed-run email first; Healthchecks after period plus grace; one watchdog issue; the backlog drains after the fix | **The invalid token** (11:56:58 to 13:24:01 UTC): GitHub's failed-run email at 12:05:00 (8 min), Healthchecks `tick` DOWN at 12:34:19 (37 min: the last ping at 11:49, plus period 15 and grace 30), and the watchdog's issue `missed:tick/poll` at 13:19:40 (83 min). No upstream issue came during it, so there was no backlog: the first tick after the fix read upstream with HTTP 200 and lost 0. **The silent success:** not run yet. The first try broke the backup clock instead, for 15 h 41 min (DECISIONS.md, Nov 6). |
| Nov 25 | GD2: the model provider unreachable for 60 minutes | the circuit breaker stops claims; the watchdog opens an issue; 0 lost and 0 dead letters | pending (a fake 3-hour outage runs in CI: `tests/test_outage.py`) |
| Dec 9 | GD4: a lenient judge prompt | the judge drops to advisory; the code checks still decide | pending |
