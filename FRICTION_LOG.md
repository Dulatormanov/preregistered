# Friction log

What was harder than it should be, and what it cost.

## 2026-11-04 (Day 0)

- A page of 100 upstream issues is about 0.5 MB, and on the laptop's connection one download was cut off. Pages are now 30 issues.
- The laptop's `gh` token cannot change notification settings (`updateSubscription` needs the `notifications` scope), so unsubscribing from the Notary log was one click in the browser instead.
- The first tick posted its anchor, then failed at the Healthchecks ping: `curl: (3) URL rejected: Malformed input to a URL function`. The pasted `HC_TICK_URL` secret most likely ended with a copied newline. Saving it again with `printf '%s' URL | gh secret set` and re-running the failed job fixed it, in about 3 minutes.
