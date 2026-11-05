# ADR-004: hash-bound consent for the one governed write

Status: accepted, 2026-11-05.

## Problem

The posting says an agent "may never autonomously write a commitment", and asks for that to be "structurally impossible rather than merely forbidden". This project has one write that changes something outside its own repo: one label on one sandbox issue. It must happen only after a person approved exactly that change, and an approval must not be reusable for any other change.

## Options

1. **A prompt rule** ("never write without approval"). Forbidden, not impossible: the model holds the token.
2. **A human approval of the job** (an environment with a required reviewer). The person approves a run, but not its bytes: the code that runs after the approval could write something else.
3. **Hash-bound consent.** The plan job saves the exact payload and its SHA-256 before anyone approves. The approval must quote the hash. The gateway sends only that payload, and the database lets one approval be used once.

## Decision

Option 3, on top of option 2.
- **The bytes are fixed first.** `gateway/propose.py` saves the day's bundle with `prereg.propose_bundle`, which checks the hash itself. There is one bundle per day, and rows are never changed.
- **The approval quotes the bytes.** The apply job waits in the environment `sandbox-write`: the owner is the required reviewer, prevent self-review is on, and only main may deploy. The owner first reads the bundle with `make show-bundle`, then approves with a comment that contains the first 12 characters of its hash. The gateway reads that comment from GitHub's own approval history of the run.
- **One approval, once.** `prereg.claim_consent` inserts into `consent_claims`, whose primary key is the bundle, and whose foreign key is the pair (bundle, hash). A second claim fails with 23505, and a claim with another hash with 23503. `prereg.record_write` refuses to log a write that has no claim.
- **One shape.** `gateway/payload.py` accepts only "add this one label to this one sandbox issue": no assignee, milestone, state, title, body, issue type or field. `gateway/transport.py` is the only code that sends requests with the write token: add a label, remove it, and read an issue back.
- **No side door.** `probes/closure.py` lists every label that a sandbox workflow reacts to, and the gateway refuses those labels.
- **A kill switch** (`prereg.switches`): the gateway writes only while the newest row says on, and with no row it is off.

`tests/test_enforcement.py` sends 18 hostile requests; each is refused with zero write calls.

## What it does not stop

- The owner's own GitHub login can approve, and the write token itself, used outside the gateway, can do more than the gateway allows. The live probes of every promotion run show both: the gateway refuses to assign, close or set a milestone, while the same token used directly can assign (undone at once), and a side-door label added directly makes a sandbox workflow close an issue (reopened). That is why the token exists only in the environment, and only the apply job gets it.
- The gateway trusts `results/sealed.json` for the promoted areas, and `sandbox/targets.toml` for the issues it may label. Both change only by pull request, through the gate.

## What would change my mind

- GitHub adds a fine-grained permission that allows only labels. Then the token itself could not assign or close, and the probes' LANDED rows would become DENIED.
