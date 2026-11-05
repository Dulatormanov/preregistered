"""The gateway's enforcement (gateway/, db/013_consent.sql) on the test database, with a fake GitHub transport:
18 hostile requests are refused with zero write calls, one approved bundle lands once, and the database itself
keeps the rules: one approval used once, only for the exact hash, no write logged without a claim.

  PREREG_TEST_ADMIN_URL=... python tests/test_enforcement.py
"""
import hashlib
import itertools
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from setup_test_db import admin_url, role_url  # noqa: E402
from gateway import gateway  # noqa: E402
from gateway.payload import SANDBOX, canonical  # noqa: E402

TARGET = 22  # a synthetic target in sandbox/targets.toml
DOORS = {"probe-side-door"}


class FakeTransport:
    def __init__(self):
        self.writes, self.labels = 0, []

    def add_label(self, issue, label):
        self.writes += 1
        self.labels.append(label)
        return 200, "req_add", {}

    def remove_label(self, issue, label):
        self.writes += 1
        return 200, "req_remove", {}

    def read_issue(self, issue):
        return 200, "req_read", {"labels": [{"name": n} for n in self.labels]}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def owner(c, sql, *args):
    c.execute("set role prereg_owner")
    try:
        return c.execute(sql, args).fetchone()
    finally:
        c.execute("reset role")


def bundle(a, n, payload, digest=None, synthetic=True):
    """A consent row on its own day, as the owner (the plan job may save only one a day)."""
    return owner(a, "insert into prereg.consent (day, bundle, payload, payload_sha256) values (%s, %s, %s, %s)"
                    " returning id", date(2026, 1, 1) + timedelta(days=n), Jsonb({"synthetic": synthetic}), payload,
                 digest or sha(payload))[0]


def approval(digest, login="Dulatormanov"):
    return [{"state": "approved", "user": {"login": login}, "comment": f"checked with make show-bundle: {digest[:12]}"}]


def main():
    good = canonical(TARGET, "frontend")
    with psycopg.connect(admin_url(), autocommit=True) as a, psycopg.connect(role_url("gateway_svc"), autocommit=True) as g:
        assert g.execute("select prereg.switch_enabled()").fetchone()[0] is False  # off until the owner turns it on
        owner(a, "select prereg.set_switch(true, 'test')")

        days = itertools.count(1)

        def ask(payload, approvals=None, digest=None, synthetic=True):
            n = next(days)
            consent = bundle(a, n, payload, digest, synthetic)
            t = FakeTransport()
            landed, reason = gateway.apply(g, consent, f"run-{n}", approvals or approval(digest or sha(payload)), t, DOORS)
            return landed, reason, t.writes, consent

        def shaped(**extra):  # a canonical payload with more fields than the one shape allows
            return json.dumps({"issue": TARGET, "label": "frontend", "repo": SANDBOX, **extra}, sort_keys=True,
                              separators=(",", ":"))
        hostile = {
            "extra assignees": (shaped(assignees=["someone"]),), "a milestone": (shaped(milestone=1),),
            "a closed state": (shaped(state="closed"),), "a new title": (shaped(title="x"),),
            "a new body": (shaped(body="x"),), "an issue type (Check 15)": (shaped(type="Bug"),),
            "an issue field (Check 15)": (shaped(fields={"priority": "high"}),),
            "two labels": (json.dumps({"issue": TARGET, "label": ["frontend", "auth"], "repo": SANDBOX}, sort_keys=True,
                                      separators=(",", ":")),),
            "another repo": (json.dumps({"issue": TARGET, "label": "frontend", "repo": "supabase/supabase"}, sort_keys=True,
                                        separators=(",", ":")),),
            "a payload not in canonical form": (good.replace(",", ", "),),
            "a payload that does not have its hash": (good, "0" * 64),
            "a label that was not promoted": (good, None, False),
            "the side-door label": (canonical(TARGET, "probe-side-door"),),
            "an issue that is not a target": (canonical(1, "frontend"),),
        }
        refused = 0
        for name, args in hostile.items():
            payload, digest, synthetic = args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else True
            landed, reason, writes, _ = ask(payload, None, digest, synthetic)
            assert not landed and writes == 0, (name, reason, writes)
            refused += 1
        no_hash = [{"state": "approved", "user": {"login": "Dulatormanov"}, "comment": "looks fine"}]
        for name, approvals in (("an approval without the hash", no_hash),
                                ("an approval by someone else", approval(sha(good), login="someone-else"))):
            landed, reason, writes, _ = ask(good, approvals)
            assert not landed and writes == 0, (name, reason)
            refused += 1

        landed, reason, writes, consent = ask(good)  # the one approved bundle lands, once
        assert landed and writes == 1, reason
        t = FakeTransport()
        again = gateway.apply(g, consent, "run-again", approval(sha(good)), t, DOORS)  # the same approval twice
        assert again[0] is False and "already used" in again[1] and t.writes == 0
        refused += 1
        owner(a, "select prereg.set_switch(false, 'test: the owner pulls the switch')")
        landed, reason, writes, _ = ask(canonical(23, "self-hosted"))
        assert not landed and writes == 0 and "kill switch" in reason
        refused += 1
        assert refused == 18, refused
        steps = [s for (s,) in a.execute("select step from prereg.writes where consent_id = %s order by id",
                                         [consent]).fetchall()]

        # The database's own rules, whatever the code does.
        for sql, args, error in (
                ("select prereg.claim_consent(%s, %s, 'r', 'o', 'h')", [consent, sha(good)], psycopg.errors.UniqueViolation),
                ("select prereg.claim_consent(%s, %s, 'r', 'o', 'h')", [bundle(a, 99, good), "0" * 64],
                 psycopg.errors.ForeignKeyViolation),
                ("select prereg.record_write(%s, 'sent', 'add_label', null, null, null)", [bundle(a, 98, good)],
                 psycopg.errors.InvalidParameterValue)):
            try:
                g.execute(sql, args)
                raise AssertionError(f"allowed: {sql}")
            except error:
                pass
    with psycopg.connect(role_url("proposer"), autocommit=True) as p:
        try:
            p.execute("select prereg.propose_bundle('{}', %s, %s)", [good, "0" * 64])
            raise AssertionError("a bundle with the wrong hash was saved")
        except psycopg.errors.InvalidParameterValue:
            pass
        p.execute("select prereg.propose_bundle('{}', %s, %s)", [good, sha(good)])
        try:
            p.execute("select prereg.propose_bundle('{}', %s, %s)", [good, sha(good)])
            raise AssertionError("two bundles in one day")
        except psycopg.errors.UniqueViolation:
            pass
    assert steps == ["sent", "landed", "read_back", "refused"], steps
    # The plan job's choices: one synthetic target a day in turn, and no demoted area.
    from gateway.propose import choose, demoted
    assert choose([1, 2, 3], date(2026, 11, 5)) != choose([1, 2, 3], date(2026, 11, 6))
    assert not demoted({"frontend": (20, 10)}, "frontend")  # the upper Wilson end is 0.70: still above the bar
    assert demoted({"frontend": (20, 5)}, "frontend") and not demoted({}, "auth")  # 0.47; and no live record yet
    print(f"ok: {refused} hostile requests refused with zero write calls; one approved bundle landed once;"
          " the database keeps one claim per approval, the exact hash, and no write without a claim")


if __name__ == "__main__":
    main()
