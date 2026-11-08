Independent project, not affiliated with Supabase.

# Design

## The problem

A team that lets agents work on its behalf needs three things it cannot get from a demo: proof that an agent's results were not picked after the fact, a gate that stops a worse agent before it ships, and a structure in which an agent cannot write a commitment on its own. Most agent projects show a good run. This one is built to show a run that could not have been chosen afterwards.

## Who it serves

- **A platform team that runs many agents:** the registry, one database login per job, the gate and the alarms are the parts it would reuse for its thirtieth agent.
- **A reader who doubts the numbers:** every guess is locked before the label that judges it exists, and `make verify` recomputes the whole log from public data.
- **The maintainers of the repo it reads:** nothing is ever written to their repositories, and nothing about a person is published.

## Three options

1. **An offline benchmark** on old issues. Cheap and fast, but the labels already exist, so nobody can tell a result from a choice, and a model may have seen the issues in training.
2. **A live bot on the real repo** that labels issues. It would be judged by real use, but it writes to someone else's project without asking, which this project never does.
3. **Live, pre-registered predictions** on the real repo, read only, each locked by a public hash minutes after the issue opens, and scored later by the labels the maintainers add on their own; a guess counts only if it was locked before the first of them. The one write the system may make goes to its own sandbox, through a gateway, after a human approves the exact bytes.

## Decision

Option 3, with a sealed set from option 1 next to it: 151 older issues, hashed and anchored before any tuning, and scored once, so a model check has more than the few live issues of a three-week window. The details are in the ADRs: the runtime (001), Postgres as the only store (002), the queue (003), hash-bound consent (004), the gate's statistics (005), the ground truth (006) and the contact budget (008).
