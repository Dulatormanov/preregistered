# ADR-006: what counts as the truth for a guess

Status: accepted for v1, 2026-11-05. PREREGISTRATION.md v1 fixes the values before the live window opens.

## Problem

A guess is right if it names the area a maintainer gives the issue. But not every label is a maintainer's judgment. Issue forms add `bug`, `external-issue` and `to-triage` when the issue is opened. Bots and agents add labels too. And labels can come days or weeks later.

## Decision

The rules are in `rules/ground_truth.toml` and the code is in `golden/truth.py`.
- **The area** of an issue is the area of its first counting label. A counting label maps to an area, is added within 14 days of the issue's creation, and is added by a human (GitHub actor type `User`) who is not the issue's author.
- **`needs_details`** is true if `awaiting-details` was added the same way.
- **An issue with no counting area label is not scorable.**
- **The map** sends each Supabase label to one of the six areas, or to an ignore list. A label in neither list is "unknown", and the daily outcomes job opens an alert for it. On 2026-11-05, every one of the repo's 121 labels was in exactly one list.
- **The switches** change one rule at a time, for the sensitivity table: a window of 7, 14 or 28 days, template labels in or out, agent labels in or out, and rare areas pooled into "other" or dropped.

## What the data showed (Check 12)

- **Dev set:** 537 issues created May 1 to Sep 19. Under the default rule, 186 are scorable (35%): frontend 103, other 32, documentation 16, self-hosted 13, postgres 12, auth 10. needs_details is true for 82. The counts are in `golden/v1/dev_counts.json`.
- **Sealed set:** 151 issues created Sep 20 to Oct 31. The check prints only "enough" or "not enough", so nobody sees the labels before the sealed set is scored once. Only frontend has enough (at least 15). Its labels are not final until 2026-11-14.
- **So only frontend can pass the promotion bar.** If it fails, the governed write runs on synthetic sandbox issues, and the bar is never lowered.

## What would change my mind

- Maintainers start labelling through a bot. Then the agent-label switch decides, and v1 says which way.
- A new area label appears often. Then it joins the map by pull request, and the change is written in DECISIONS.md.

## Update, 2026-11-05 (Build day 8)

- **The same rule in three places, kept equal.** `golden/truth.py` scores the dev and sealed sets; `prereg.v_truth` (`db/012_value_views.sql`) applies the rule in SQL for the value views, with the mapping copied from `rules/ground_truth.toml` v1 into `prereg.label_areas`; and `tools/public_tables.py` applies it to GitHub's public label events, for anyone. `tests/test_tables.py` and `tests/test_views.py` check that each one counts what the rule says.
- **The time rule is part of the live score:** a guess counts only if the anchor that covers it was posted before the issue's first counting label.
- **Anyone can recompute it.** Fourteen days after a guess is saved, `notary/reveal.py` publishes it on the `data` branch. `make verify` recomputes every anchor from that copy, and `make tables-public` scores it from the public label events, with a read-only token.
