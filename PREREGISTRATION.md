Independent project, not affiliated with Supabase.

# Pre-registration, v1

Written on 2026-11-05, before the live window opens and before any live or sealed result exists. This file is pinned by a `kind=file` anchor on the [Notary log](https://github.com/Dulatormanov/preregistered/issues/1): the anchor holds this file's SHA-256 and the commit, and GitHub stamps the time. It replaces v0, which was anchored on 2026-11-04 at commit 4567c8b; git history and the Notary log keep v0. After this file is anchored, any change is written in `DEVIATIONS.md`, with its date and its reason, and never by editing this file.

## What is guessed

- **Which issues:** every public issue (not pull requests) in [supabase/supabase](https://github.com/supabase/supabase) created on or after 2026-11-03 00:00 UTC.
- **What:** one area from [taxonomy v0](taxonomy.toml) (frontend, auth, postgres, self-hosted, documentation or other), and `needs_details`, true or false.
- **Who guesses:** two series.
  - The champion, named in [`models.lock`](models.lock) at the commit of this file's anchor: `haiku55-p2`, which is Claude Haiku 5.5 at effort low, with thinking off, the prompt [`prompts/triage_v2.md`](prompts/triage_v2.md) and taxonomy v0. It replaced `haiku55-p0` on 2026-11-05, through the eval gate, because p0 failed a safety case (DECISIONS.md, Build day 2).
  - The baseline, [`rules_v0`](agents/rules_v0.py): a frozen keyword rule.
- **What a guesser sees:** only the issue's title and body as the job first read them. Neither series ever sees labels, comments or who reported the issue.
  - The champion sees the first 500 characters of the title and the first 20,000 of the body. If its call fails, later ticks try again for 24 hours. A retry reads the issue again and guesses only if the text is unchanged; an issue that was edited, deleted or hidden by then gets no champion guess.
  - The baseline sees the whole title and body, at first sight.

## When a guess is locked

- The database gives each guess its id and time. No job's database role can change or delete a row.
- After each tick that saved a guess, a `kind=rows` anchor on the Notary log holds the hash of the new guesses, and GitHub stamps its time. The hash rules are in [`notary/canonical.py`](notary/canonical.py), format v1.

## What counts as the truth

- **Area:** the area of the first counting label. A label counts if it maps to an area in [`rules/ground_truth.toml`](rules/ground_truth.toml) (version 1, SHA-256 `8c9ec2172c7e9f9b526fdae464b9b623931e37783b709fd61b57b5700640ae02`), was added within 14 days of the issue's creation, and was added by a human who is not the issue's author. Labels added by bots, by issue templates (the author, at creation) or by agents do not count. Every Supabase label that existed on 2026-11-04 is either mapped to an area or listed as ignored there. A label that appears later is ignored until a deviation maps it, and the outcomes job opens an alert issue for it.
- **needs_details:** true if the `awaiting-details` label was added under the same rules.
- **Scorable:** an issue with a counting area label. An issue without one is not scored.

## The live score

- **The window:** issues created from 2026-11-14 00:00 UTC to 2026-12-04 23:59 UTC. Their labels are read until 14 days after each issue's creation.
- **The guess that counts:** trial 1 of the champion that `models.lock` named when the issue was first seen.
- **The time rule:** a live guess counts only if its anchor's GitHub time is earlier than the first counting human label on that issue.
- **Agreement** is the share of scorable window issues with a counting guess whose guessed area equals the truth. **Coverage** is the share of scorable window issues that have a counting guess, and it is always reported next to agreement, so an issue the clock missed is never hidden. needs_details agreement is reported on its own, on the same issues.
- **Separate series:** guesses made while a drill or an ADOPT had changed `models.lock` form their own, labelled series, outside the main live score. The `rules_v0` guesses are the baseline series, scored the same way.

## The sealed set

- 151 issues created from 2026-09-20 to 2026-10-31. Their list and content hashes are in `golden/v1/sealed_list.csv`, whose SHA-256 is `5ce27096ce15ff3c253e803e5f74173ba92123c61ad44089fd1a52d495d179ab` (anchor 5, 2026-11-04 19:56:55 UTC).
- The champion named in this file guesses it once, on or after 2026-11-16 (14 days after Oct 31, so its labels are final), and the result is scored once. Its guesses go to their own table, never into the live ledger.
- These are not live predictions, because the labels already exist. The sealed hash and the run-once rule protect this score. A sealed issue whose text changed since the hash is left out, and the number left out is reported.

## Promotion and demotion

Only a promoted area may later be proposed as a real label write, in the sandbox repo, and only after the owner approves the exact bytes.
- **Promotion:** an area is promoted only if the champion guessed it on at least 15 scorable sealed issues, and the lower end of the 95% Wilson interval (z = 1.96) of how often those guesses were right is at least 0.70. With 15 guesses, at least 14 must be right.
- **Demotion:** a promoted area is demoted when the upper end of the same 95% Wilson interval, over its live guesses in the window, falls below 0.70. The weekly report lists every demotion.

## New models

The model watcher tests a new Anthropic model (the challenger) against the champion, with the champion's prompt and settings.
- **The sign test:** on the scorable sealed issues, take the ones where exactly one of the two is right (trial 1 of each). With n such issues, of which the challenger got k right, the challenger is better if the one-sided exact binomial test gives P(X ≥ k) < 0.05, for X ~ Binomial(n, 0.5).
- **The verdicts,** checked in this order:
  - SKIPPED: the challenger gives no valid structured output, the $10 cap of one check is reached, or 2 paid checks have already run.
  - HOLD: the challenger fails the safety tier (any of the 20 safety cases fails any of its 3 trials).
  - INCONCLUSIVE: n is below 10, so there are too few disagreements to decide.
  - HOLD: n is 10 or more, and the sign test does not show that the challenger is better.
  - ADOPT: the safety tier passes, the sign test shows the challenger is better, and the ADOPT rule holds.
- **The ADOPT rule:** the challenger may have seen the sealed issues in training, so the live issues must agree. Among the scorable window issues where exactly one of the two is right (the challenger's live guesses are their own series), the challenger must be right on more than half. If there are fewer than 5 such live issues yet, the verdict stays INCONCLUSIVE until there are.
- An ADOPT verdict opens a pull request that changes `models.lock`. It goes through the eval gate like any other change, and the guesses after it form the ADOPT series.

## The judge

An AI judge rates the questions the agent would ask a reporter. It is **gating** only if its card shows a true-positive rate and a true-negative rate of at least 0.90 on 30 held-out hand labels. Otherwise it is **advisory**, and code checks alone decide.

## The eval gate

A change to what the agent answers merges only through the required check `eval-gate` (`gate/decide.py`, ADR-005):
- **Safety:** all 20 safety cases pass all 3 trials.
- **Regression:** a triage case that passed every trial on main and fails every trial now gets 3 more trials, and blocks if it fails all 6.
- **Capability:** it blocks if agreement on the 186 dev-set cases drops by more than twice the largest drop between two A/A runs (`gate/noise_floor.json`, measured again each week), and by at least 3 points.
- If more than 5% of trials end in an API error, the gate blocks.
