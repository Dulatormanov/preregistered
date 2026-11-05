Independent project, not affiliated with Supabase.

# The judge's card

- **Verdict: advisory.** The rule (PREREGISTRATION.md v1): gating only if the true-positive rate and
  the true-negative rate on the 30 held-out hand labels are both at least 0.90.
- **Held-out labels:** 30 good and 0 bad questions, labelled by hand before the judge saw them.
- **True-positive rate** (the judge says good when the label says good): 0.57.
- **True-negative rate** (the judge says bad when the label says bad): none (no such labels).
- **Judge:** claude-haiku-5-5, effort low, thinking off; rubric `judges/rubric.md`, SHA-256
  `f91553c38c02a57ef38907feb7dd4693ae7bda205704310a5b51a84e135a1a8e`.
- **Made on** 2026-11-05. The questions, the labels and the judge's answers stay in the private
  database, so this card holds counts and rates only.
