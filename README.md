Independent project, not affiliated with Supabase.

# preregistered

Every 15 minutes, a job reads new public issues in [supabase/supabase](https://github.com/supabase/supabase) and saves one label guess for each. Each guess is locked when the job first sees the issue, and the labels the issue already had are saved with it:

- the database role that saves guesses can only add rows, and the database sets each row's id and time;
- after each tick that saved a guess, a SHA-256 chain hash of the new guesses is posted on the pinned [Notary log](https://github.com/Dulatormanov/preregistered/issues/1), and GitHub stamps the time.

Later, the labels that maintainers add show how often the guesses agreed.

It only reads public data. It never writes anything to Supabase's repositories, and it stores numbers, labels and hashes, never issue text.

**Status: Day 0 (2026-11-04).** The guesser is a keyword rule, [`agents/rules_v0.py`](agents/rules_v0.py). A model takes over on Day 1. The rules for recomputing every hash are in [`notary/canonical.py`](notary/canonical.py).
