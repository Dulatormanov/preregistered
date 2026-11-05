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
| prereg-read | add the label probe-label to the probe issue | DENIED (want DENIED) | 403 | 26C0:20C29C:4AE33A9:F69016E:6AEC5322 |
| prereg-sandbox-write | reach a job outside the environment | ABSENT (want ABSENT) | - | - |
| prereg-sandbox-write | add the label probe-label to the probe issue | LANDED (want LANDED) | 200 | E8A8:1C6C93:214B6B7:6D383CD:6AEC5D1D |
| prereg-sandbox-write | remove the label probe-label again | LANDED (want LANDED) | 200 | E8A9:10D8DA:F4BC2D:325C255:6AEC5D1E |

From probe run 42006701215 on 2026-11-05. Its write job waited until the owner approved it, at 10:40 UTC. `dispatch.yml` had started the run, so prevent self-review did not block that approval (Check 13 passed).

## The governed write (Build day 6)

Every promotion run (`promote.yml`, started through `dispatch.yml`) ends with the live probes of `probes/probe.py gateway`, on the sandbox's probe issue and the side-door target (sandbox issue 25). The apply job is the one named job that uses the write token directly, outside the gateway: to show what the token itself can do, and to undo it at once. Each undo runs whatever happens, its result is a row of its own, and both issues must read back as they began. The side door counts only if this run's label closed the issue; a target that starts closed or labelled is an ERROR, never a LANDED.

| Probe | Want | Result |
|---|---|---|
| the gateway is asked to assign, close and set a milestone | REFUSED, and the issue reads back unchanged | REFUSED, REFUSED and REFUSED; both issues read back as they began |
| the write token assigns the owner directly | LANDED, then removed | LANDED (201, E850:2F79D4:42A77AD:DA7A8B6:6AEC5DEA), then removed (200, E851:1F3CB:424FFAC:D987175:6AEC5DEB) |
| the write token adds `probe-side-door` directly | LANDED: side_door_demo.yml closes the issue after this label (then reopened, checked) | LANDED (200, E852:27930C:4268FD7:D97EFAB:6AEC5DEC); side_door_demo.yml closed the issue; reopened (200, E849:BF082:4335921:DBD3665:6AEC5DF7); label removed (200, E84A:1877A7:43080C3:DC71419:6AEC5DF9) |
| the gateway is asked to add `probe-side-door` | REFUSED | REFUSED |

From promotion run 42012858329 on 2026-11-05. Its one write was bundle 1: the label `documentation` on sandbox issue 24. The bundle was synthetic, because no area can pass the sealed bar before the sealed run, and it names `haiku55-p2-drill`, the rollback drill's id for the same setup as `haiku55-p2`. The owner approved the apply job with a comment that quoted the first 12 characters of the payload hash, `71ee36078612`. The gateway logged three steps for that one write: sent, landed (200, E84C:2F9B:4356C14:DC60B52:6AEC5DE8), and read back (the label is there). The kill switch was on only for this run, from 10:41:27 to 10:44:53 UTC.

- **Check 15:** issue types and issue fields do not exist in this personal sandbox repo (checked on 2026-11-05: GraphQL `issueTypes` is null for a user's repo, and no issue has a type or a field). The gateway refuses both anyway: its one payload shape has no such keys.

## The backup clock

`prereg-backup-clock` is a fine-grained token with Actions read and write, on this repo only. It exists in one place: `~/prereg/token` on the owner's server, readable by the owner's user only. Cron runs `ops/backup_clock.py` next to it 12 minutes after each tick slot, and the script starts `tick.yml` only if GitHub's schedule has not (ADR-001). The token can start, re-run, cancel and delete this repo's workflow runs, and turn its workflows on or off; the watchdog alerts on a workflow that is off. It cannot change code, issues, labels or secrets.

## Other side doors

- **Webhooks on the sandbox:** 0, checked 2026-11-05 with the API.
- **Linked GitHub Projects and installed GitHub Apps:** the owner's CLI token cannot list them, because GitHub asks for other scopes. The owner checks both in the browser (Settings > Applications > Installed GitHub Apps, and the sandbox's Projects tab). An app installed on all of the owner's repositories could write to the sandbox, so it would be a side door.
- **The side door kept on purpose:** `side_door_demo.yml` in the sandbox closes any issue that gets the label `probe-side-door`. `probes/closure.py` finds it, and the gateway refuses that label.
