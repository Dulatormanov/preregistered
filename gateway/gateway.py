"""The gateway: the only code that may write with the sandbox write token, and only one approved label on one
sandbox issue (Build day 6, ADR-004). The owner's approval is bound to the payload's SHA-256, and is used once.

  GATEWAY_DB_URL=... PREREG_SANDBOX_WRITE=... GH_TOKEN=... python -m gateway.gateway CONSENT_ID
Every check refuses with a reason, and a refusal sends no write at all:
1. the kill switch is on;
2. the bundle's payload has its hash, and has the one payload shape (gateway/payload.py);
3. no sandbox workflow reacts to the label (probes/closure.py), the issue is a target (sandbox/targets.toml), and
   the label is promoted by the sealed score, or the bundle is synthetic (no area has passed the bar yet);
4. this run has exactly one approval, by the owner, and its comment quotes the first 12 characters of the hash;
5. the approval is claimed once: prereg.claim_consent fails on a second claim, or on any other hash.
Then it sends the one write, logs each step in prereg.writes, and reads the issue back.
"""
import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = "Dulatormanov"
AREAS = ("frontend", "auth", "postgres", "self-hosted", "documentation", "other")


class Refused(Exception):
    pass


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def allowed(issue, label, bundle):
    """True if the issue is a target, and the label is promoted by the sealed score, or the bundle is synthetic."""
    sealed = ROOT / "results/sealed.json"
    promoted = json.loads(sealed.read_text())["promoted"] if sealed.exists() else []
    targets = {t["issue"] for t in tomllib.loads((ROOT / "sandbox/targets.toml").read_text())["target"]}
    return issue in targets and (label in promoted or (bundle.get("synthetic") is True and label in AREAS))


def check(db, consent_id, approvals, side_doors):
    """(issue, label, payload hash, approval) for a bundle that passes every check; Refused otherwise."""
    from gateway import payload
    if not db.execute("select prereg.switch_enabled()").fetchone()[0]:
        raise Refused("the kill switch is off")
    bundle, text, digest = db.execute("select * from prereg.get_bundle(%s)", [consent_id]).fetchone()
    if text is None:
        raise Refused("there is no such bundle")
    if sha256(text) != digest:
        raise Refused("the payload does not have its hash")
    try:
        issue, label = payload.parse(text)
    except ValueError as e:
        raise Refused(f"not the one payload shape: {e}")
    if label in side_doors or "*" in side_doors:
        raise Refused(f"a sandbox workflow reacts to the label {label}")
    if not allowed(issue, label, bundle):
        raise Refused(f"the label {label} may not go on issue {issue}: not a target, or not promoted")
    approved = [a for a in approvals if a.get("state") == "approved"]
    if len(approved) != 1:
        raise Refused(f"{len(approved)} approvals of this run, not exactly one")
    a = approved[0]
    if (a.get("user") or {}).get("login") != OWNER:
        raise Refused("the approval is not the owner's")
    if digest[:12] not in (a.get("comment") or ""):
        raise Refused("the approval does not quote the first 12 characters of the payload hash")
    return issue, label, digest, a


def apply(db, consent_id, run_id, approvals, transport, side_doors):
    """(landed, reason): one governed write, or a refusal that sent nothing."""
    import psycopg
    known = db.execute("select (select payload from prereg.get_bundle(%s)) is not null", [consent_id]).fetchone()[0]
    try:
        issue, label, digest, a = check(db, consent_id, approvals, side_doors)
        try:
            db.execute("select prereg.claim_consent(%s, %s, %s, %s, %s)",
                       [consent_id, digest, run_id, a["user"]["login"], sha256(a["comment"])])
        except psycopg.errors.UniqueViolation:
            raise Refused("this bundle's approval was already used")
        except psycopg.errors.ForeignKeyViolation:
            raise Refused("the claim does not match the bundle's hash")
    except Refused as e:
        db.execute("select prereg.record_write(%s, 'refused', null, null, null, %s)", [consent_id if known else None, str(e)])
        return False, str(e)
    db.execute("select prereg.record_write(%s, 'sent', 'add_label', null, null, null)", [consent_id])
    status, request_id, _ = transport.add_label(issue, label)
    db.execute("select prereg.record_write(%s, %s, 'add_label', %s, %s, null)",
               [consent_id, "landed" if 200 <= status < 300 else "failed", status, request_id])
    status, request_id, it = transport.read_issue(issue)
    there = label in [lab["name"] for lab in it.get("labels", [])]
    db.execute("select prereg.record_write(%s, 'read_back', 'read_issue', %s, %s, %s)",
               [consent_id, status, request_id, "the label is there" if there else "the label is missing"])
    return there, f"the label {label} is on sandbox issue {issue}" if there else "the write did not land"


def approvals_of(run_id, token):
    """This run's approval history: GitHub's own record of who approved it, and their comment."""
    import urllib.request
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}/approvals",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "preregistered"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    import psycopg
    from gateway.transport import Transport
    from probes.closure import side_door_labels
    run_id, consent_id = os.environ["GITHUB_RUN_ID"], int(sys.argv[1])
    approvals = approvals_of(run_id, os.environ["GH_TOKEN"])
    transport = Transport(os.environ["PREREG_SANDBOX_WRITE"])
    with psycopg.connect(os.environ["GATEWAY_DB_URL"], autocommit=True) as db:  # gateway_svc: functions only
        landed, reason = apply(db, consent_id, run_id, approvals, transport, side_door_labels(os.environ["GH_TOKEN"]))
    print(f"gateway: {'LANDED' if landed else 'REFUSED'}: {reason}; {transport.writes} writes sent")
    sys.exit(0 if landed else 1)


if __name__ == "__main__":
    main()
