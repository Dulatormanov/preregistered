---
stage: triage
interface: github-issue
samples: golden/v1/dev_truth.csv
motivation: The live job guesses one area for every new issue, and the later human label decides if it agreed; this eval asks the same of the 186 scorable dev-set issues.
---

Read one GitHub issue of supabase/supabase, its title and body only, and answer with one area of
[taxonomy v0](../../taxonomy.toml) and needs_details. A case passes when the area equals the first counting
human label (ground truth v1, rules/ground_truth.toml). The issue text is read from GitHub at run time; a case
whose text changed since the golden set was built is skipped.
