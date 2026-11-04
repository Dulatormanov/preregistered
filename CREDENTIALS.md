Independent project, not affiliated with Supabase.

# Credentials: what each one can do, and the proof

`credentials.toml` lists every secret: what it can do, what it must never do, and when it expires. It also holds the exact privilege matrix that `tests/test_privilege_matrix.py` checks. This page holds the proof from live probes.

## The human gate

The sandbox write token, `prereg-sandbox-write`, exists in one place only: the GitHub environment `sandbox-write` of this repo. GitHub releases it to a job only after the owner approves that job.

| Rule of the environment | Setting (checked 2026-11-05 with the API) |
|---|---|
| Required reviewer | Dulatormanov |
| Prevent self-review | on: nobody can approve a run they started |
| Administrators can bypass | no |
| Branches that may deploy | `main` only |

A run that needs the write token is always started by `dispatch.yml`, so its triggering actor is the bot. That is why the owner can approve it (Check 13).

## Live probes on the sandbox's probe issue

`probes/probe.py`, run by `probe.yml` and started through `dispatch.yml`. Each row is one real request, with GitHub's request id.

| Token | Action | Result | HTTP | Request id |
|---|---|---|---|---|
| pending: the first probe runs once `prereg-sandbox-write` exists | | | | |

## Other side doors

- **Webhooks on the sandbox:** 0, checked 2026-11-05 with the API.
- **Linked GitHub Projects and installed GitHub Apps:** the owner's CLI token cannot list them, because GitHub asks for other scopes. The owner checks both in the browser (Settings > Applications > Installed GitHub Apps, and the sandbox's Projects tab). An app installed on all of the owner's repositories could write to the sandbox, so it would be a side door.
- **The side door kept on purpose:** `side_door_demo.yml` in the sandbox closes any issue that gets the label `probe-side-door`. The gateway (Build day 6) must refuse that label.
