Independent project, not affiliated with Supabase.

# preregistered

Every 15 minutes, a job reads new public issues in [supabase/supabase](https://github.com/supabase/supabase) and saves two label guesses for each, from the text it saw when it first read the issue. The labels the issue already had then are saved too:

- a keyword baseline, at first sight;
- a Claude Haiku 5.5 guess, in the same tick. If that call fails, later ticks try again for 24 hours, but only while the issue is unchanged.

Each guess is locked:

- the database role that saves guesses can only add rows, and the database sets each row's id and time;
- after each tick that saved a guess, a SHA-256 chain hash of the new guesses is posted on the pinned [Notary log](https://github.com/Dulatormanov/preregistered/issues/1), and GitHub stamps the time.

Later, the labels that maintainers add show how often the guesses agreed.

It only reads public data. It never writes anything to Supabase's repositories, and it stores numbers, labels and hashes, never issue text.

**Status: Day 1 (2026-11-04).** Claude Haiku 5.5 guesses each new issue, as set in [`models.lock`](models.lock), and the keyword rule [`agents/rules_v0.py`](agents/rules_v0.py) guesses next to it as the baseline. The rules of the experiment are in [`PREREGISTRATION.md`](PREREGISTRATION.md), and the rules for recomputing every hash are in [`notary/canonical.py`](notary/canonical.py).
