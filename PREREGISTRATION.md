Independent project, not affiliated with Supabase.

# Pre-registration, v0

Written on 2026-11-04, before any result exists. This file is pinned by a `kind=file` anchor on the [Notary log](https://github.com/Dulatormanov/preregistered/issues/1): the anchor holds this file's SHA-256 and the commit, and GitHub stamps the time. v1 will replace this text in the same file, before the live window opens, and will be anchored the same way. Git history and the Notary log keep v0.

## What is guessed

- **Which issues:** every public issue (not pull requests) in [supabase/supabase](https://github.com/supabase/supabase) created on or after 2026-11-03 00:00 UTC.
- **What:** one area from [taxonomy v0](taxonomy.toml) (frontend, auth, postgres, self-hosted, documentation or other), and `needs_details`, true or false.
- **Who guesses:** two series.
  - The champion, named in [`models.lock`](models.lock): today `haiku55-p0`, which is Claude Haiku 5.5 at effort low, with thinking off, the prompt [`prompts/triage_v0.md`](prompts/triage_v0.md) and taxonomy v0.
  - The baseline, [`rules_v0`](agents/rules_v0.py): a frozen keyword rule.

  The setup is the one in `models.lock` at the commit named in this file's anchor.
- **What a guesser sees:** only the issue's title and body as the job first read them. Neither series ever sees labels or comments.
  - The champion sees the first 500 characters of the title and the first 20,000 of the body. If its call fails, later ticks try again for 24 hours. A retry reads the issue again and guesses only if the text is unchanged; an issue that was edited, deleted or hidden gets no champion guess.
  - The baseline sees the whole title and body, at first sight.

## When a guess is locked

- The database gives each guess its id and time. The job's database role can add rows, but it can never change or delete them.
- After each tick that saved a guess, a `kind=rows` anchor on the Notary log holds the hash of the new guesses, and GitHub stamps its time. The hash rules are in [`notary/canonical.py`](notary/canonical.py).

## What counts as the truth

- **Area:** a label from the area mapping, added within 14 days of the issue's creation, by a human who is not the issue's author. Labels added by bots, by issue templates or by agents do not count. v1 fixes the list of Supabase labels that map to each area, before the live window opens.
- **needs_details:** the `awaiting-details` label, under the same rules.

## Which guesses count

- **The live score:** issues created in the live window, from 2026-11-14 00:00 UTC to 2026-12-04 23:59 UTC. v1 confirms these dates.
- **The guess that counts:** trial 1 of the champion that `models.lock` named when the issue was first seen.
- **The time rule:** a live guess counts only if its anchor's GitHub time is earlier than the first counting human label on that issue.
- **Separate series:** guesses made while a drill or an ADOPT had changed `models.lock` form their own, labelled series, outside the main live score. The `rules_v0` guesses are the baseline series.

## Older issues

- **The dev set:** issues created from 2026-05-01 to 2026-09-19. They may be used to build and tune the champion.
- **The sealed set:** issues created from 2026-09-20 to 2026-10-31. On Nov 3 it held 151 issues.
  - Before any tuning, a hash of its issue list and content hashes is committed and anchored. That hash fixes the list.
  - The champion guesses it once, on 2026-11-16, after its labels are final, and the result is scored once.
  - These are not live predictions, because the labels already exist. The sealed hash and the run-once rule protect this score.

## What v1 adds

Before 2026-11-14 00:00 UTC, v1 adds:
- the label mapping, the window and the thresholds;
- the promotion bar and the demotion rule;
- the sign test for new models and the rule for the AI judge;
- the verdict rules (ADOPT, HOLD, INCONCLUSIVE, SKIPPED) and the ADOPT rule;
- the sealed hash.

After the window opens, any change is written in `DEVIATIONS.md` with its date and reason. A change never rewrites this file.
