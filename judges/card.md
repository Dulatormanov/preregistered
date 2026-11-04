Independent project, not affiliated with Supabase.

# The judge's card

- **Verdict: advisory, for now.** The hand labels do not exist yet: 0 of 60. Until `python -m judges.calibrate card`
  writes this card from the 30 held-out labels, the judge cannot gate, and the code checks alone decide.
- **The rule** (PREREGISTRATION.md v1): gating only if the true-positive rate and the true-negative rate on the 30
  held-out hand labels are both at least 0.90.
- **The questions:** 60 reporter questions for dev-set issues that a maintainer marked as lacking details, 30 to
  build the judge with and 30 held out. A third were written by a deliberately generic prompt, mixed in, so the
  labels have both kinds. They stay in the private database (`golden/private/judge.sqlite`, git-ignored).
