Independent project, not affiliated with Supabase.

# Deviations from the pre-registration

[PREREGISTRATION.md](PREREGISTRATION.md) v1 is never edited after its anchor. Each change is written here, with its date and its reason, and this file is pinned by a `kind=file` anchor on the [Notary log](https://github.com/Dulatormanov/preregistered/issues/1) before the change takes effect.

## Deviation 1, 2026-11-06: a shorter window, a shorter label period, an earlier sealed score

Written on 2026-11-06, before the window it sets opens (2026-11-07 00:00 UTC) and before any live or sealed result exists: no window issue has been scored, and the sealed set has never been guessed.

- **Why:** the owner applies for the job this project was built for sooner than planned, so the results must exist by about Nov 21 instead of Dec 18. The reason is time, not results.
- **The window:** issues created from 2026-11-07 00:00 UTC to 2026-11-13 23:59 UTC (v1: 2026-11-14 to 2026-12-04). Their labels are read until 7 days after each issue's creation.
- **The truth:** a label counts if it was added within 7 days of the issue's creation (v1: 14 days). 7 days was already one of v1's switches in [`rules/ground_truth.toml`](rules/ground_truth.toml), which is now version 2, SHA-256 `938dfaaf01b835534d0622666e5b12a5c0046bd5ac50d72033f109b691cd2fc2`. It differs from version 1 only in its version number, its header comment and `window_days`. The new rule applies to the live score and the sealed score; the sensitivity table shows v1's 14 days as a switch. The eval gate's 186 dev-set cases keep the truth they were built with.
- **The reveal:** a guess goes public on the `data` branch 7 days after it is saved (v1: 14 days), so it still goes public only after the labels that count are in.
- **The sealed set:** the champion guesses it once, on or after 2026-11-08 (7 days after Oct 31, so its labels are final), and the result is scored once (v1: on or after 2026-11-16).
- **What to expect:** at about 2 to 4 new issues a day, the window holds far fewer scorable issues than v1's would have, so the intervals will be wide. The final live score comes on or after 2026-11-21, when the labels of the window's last issues are final and their guesses are public.
- **Unchanged:** everything else in v1: the champion, what a guesser sees, the time rule, coverage, the separate series, promotion and demotion (demotion reads the new window), the model watcher (its ADOPT rule reads the new window) and the eval gate.
- **In the code:** `db/017_deviation_1.sql`, `rules/ground_truth.toml` v2, `tools/tables.py`, `notary/reveal.py`, `notary/verify.py` and `adopt/sealed.py` (DECISIONS.md, 2026-11-06).
