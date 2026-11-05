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

- **Where the token is saved.** Only as an environment secret: `gh secret set PREREG_SANDBOX_WRITE --env sandbox-write`. Saved without `--env`, it would be a repository secret, which any run on any branch can read with no approval. The probe checks this on every run: its first job runs outside the environment, and it fails if the token reaches it.
- **What the gate does not stop.** Anyone who holds the owner's own GitHub login can approve, and that includes the `gh` CLI token on the owner's laptop. No job and no secret in this repo can approve. So the CLI token never goes into a job, and a coding agent on the laptop must never approve. That last part is a rule, not a structure.

## Live probes on the sandbox's probe issue

`probes/probe.py`, run by `probe.yml` and started through `dispatch.yml`. Each row is one real request, with GitHub's request id. DENIED means GitHub's own refusal (HTTP 403, "Resource not accessible"). Any other failure, such as a dead token (401), a rate limit or a GitHub error, is ERROR and fails the run, so it can never pass for a denial.

| Token | Action | Result | HTTP | Request id |
|---|---|---|---|---|
| pending: the first probe runs once `prereg-sandbox-write` exists | | | | |

## The governed write (Build day 6)

Every promotion run (`promote.yml`, started through `dispatch.yml`) ends with the live probes of `probes/probe.py gateway`, on the sandbox's probe issue and the side-door target (sandbox issue 25). The apply job is the one named job that uses the write token directly, outside the gateway: to show what the token itself can do, and to undo it at once. Each undo runs whatever happens, its result is a row of its own, and both issues must read back as they began. The side door counts only if this run's label closed the issue; a target that starts closed or labelled is an ERROR, never a LANDED.

| Probe | Want | Result |
|---|---|---|
| the gateway is asked to assign, close and set a milestone | REFUSED, and the issue reads back unchanged | pending: the first promotion run |
| the write token assigns the owner directly | LANDED, then removed | pending |
| the write token adds `probe-side-door` directly | LANDED: side_door_demo.yml closes the issue after this label (then reopened, checked) | pending |
| the gateway is asked to add `probe-side-door` | REFUSED | pending |

- **Check 15:** issue types and issue fields do not exist in this personal sandbox repo (checked on 2026-11-05: GraphQL `issueTypes` is null for a user's repo, and no issue has a type or a field). The gateway refuses both anyway: its one payload shape has no such keys.

## Other side doors

- **Webhooks on the sandbox:** 0, checked 2026-11-05 with the API.
- **Linked GitHub Projects and installed GitHub Apps:** the owner's CLI token cannot list them, because GitHub asks for other scopes. The owner checks both in the browser (Settings > Applications > Installed GitHub Apps, and the sandbox's Projects tab). An app installed on all of the owner's repositories could write to the sandbox, so it would be a side door.
- **The side door kept on purpose:** `side_door_demo.yml` in the sandbox closes any issue that gets the label `probe-side-door`. `probes/closure.py` finds it, and the gateway refuses that label.
