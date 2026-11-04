"""The registry rules (agents/registry.toml), checked against every workflow file. Run: python tests/test_registry.py

CI fails when a job has no registry entry, when a job holds a secret or a permissions grant that its entry does
not list, when one job holds both a model key and a write right, or when a tier has no suite or no human gate.
The workflow files are read by a small reader made for them, which fails closed: a secret reference outside a
job, or a permissions line it cannot read, fails the test. Each rule is then shown to fire on a broken copy.
"""
import copy
import re
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = tomllib.loads((ROOT / "agents/registry.toml").read_text())
AUTONOMY = ("read_report", "carry_consented_update", "initiate_contact")


def workflow_jobs(path):
    """{job id: {"secrets", "permissions", "environment"}} for one workflow file."""
    text = path.read_text()
    lines = text.splitlines()
    assert "permissions: {}" in lines, f"{path.name}: the workflow must start from permissions: {{}}"
    bodies, current = {}, None
    for line in lines[lines.index("jobs:") + 1:]:
        if re.match(r"^\S", line):
            break  # the next top-level key
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", line)
        if m:
            current = bodies.setdefault(m.group(1), [])
        elif current is not None:
            current.append(line)
    jobs = {}
    for job, body in bodies.items():
        permissions, environment = set(), None
        for i, line in enumerate(body):
            if re.match(r"^\s+permissions:", line):
                inline = line.split(":", 1)[1].split("#")[0].strip()
                assert re.match(r"^    permissions:", line) and inline in ("", "{}"), f"{path.name}/{job}: {line.strip()}"
                for following in body[i + 1:]:
                    if not following.strip() or following.strip().startswith("#"):
                        continue  # a blank or comment line inside the block
                    if not following.startswith("     "):
                        break  # the block ends at the next key of the job
                    m = re.match(r"""^      ([a-z-]+):\s*['"]?(read|write|none)['"]?\s*(#.*)?$""", following)
                    assert m, f"{path.name}/{job}: a permissions line the reader cannot read: {following.strip()}"
                    if m.group(2) != "none":
                        permissions.add(f"{m.group(1)}: {m.group(2)}")
            m = re.match(r"^    environment:\s*([\w-]+)", line)
            if m:
                environment = m.group(1)
        jobs[job] = {"secrets": set(re.findall(r"secrets\.([A-Za-z0-9_]+)", "\n".join(body))),
                     "permissions": permissions, "environment": environment}
    in_jobs = sum(len(re.findall(r"secrets\.", "\n".join(b))) for b in bodies.values())
    assert in_jobs == len(re.findall(r"secrets\.", text)), f"{path.name}: a secret is used outside a job"
    for expression in re.findall(r"\$\{\{(.*?)\}\}", text):  # secrets['X'] or toJSON(secrets) would hide a secret
        assert not re.search(r"\bsecrets\b(?!\.[A-Za-z0-9_]+)", expression), f"{path.name}: {expression.strip()}"
    return jobs


def found_jobs():
    return {f"{p.stem}/{job}": info for p in sorted((ROOT / ".github/workflows").glob("*.yml"))
            for job, info in workflow_jobs(p).items()}


def problems(found, registry):
    entries = {e["id"]: e for e in registry["job"]}
    out = []
    for jid, info in found.items():
        e = entries.get(jid)
        if e is None:
            out.append(f"{jid}: no registry entry")
            continue
        if info["secrets"] - set(e["secrets"]):
            out.append(f"{jid}: secrets its entry does not list: {sorted(info['secrets'] - set(e['secrets']))}")
        if info["permissions"] - set(e["permissions"]):
            out.append(f"{jid}: permissions its entry does not list: {sorted(info['permissions'] - set(e['permissions']))}")
        if info["environment"] != e.get("environment"):
            out.append(f"{jid}: environment {info['environment']} is not the entry's {e.get('environment')}")
        writes = {p for p in info["permissions"] if p.endswith(": write")} | (info["secrets"] & set(registry["write_secrets"]))
        if info["secrets"] & set(registry["model_keys"]) and writes:
            out.append(f"{jid}: holds a model key and a write right ({sorted(writes)}): split it in two jobs")
    for jid, e in entries.items():
        if not jid.startswith("pg_cron/") and jid not in found:
            out.append(f"{jid}: an entry for a job that does not exist")
        if e["tier"] not in registry["tier"]:
            out.append(f"{jid}: unknown tier {e['tier']}")
        if e["autonomy"] not in AUTONOMY:
            out.append(f"{jid}: unknown autonomy {e['autonomy']}")
        if e["suite"] != "ci" and not (ROOT / "suites" / f"{e['suite']}.toml").exists():
            out.append(f"{jid}: no suite {e['suite']}")
        if "cadence_min" in e and not {"at_minute", "grace_min", "evidence"} <= e.keys():
            out.append(f"{jid}: a cadence needs at_minute, grace_min and evidence")
    for name, tier in registry["tier"].items():
        if not tier.get("suite") or not tier.get("human_gate"):
            out.append(f"tier {name}: no suite or no human gate")
    return out


def main():
    found = found_jobs()
    assert not problems(found, REGISTRY), problems(found, REGISTRY)

    def broken(change):
        reg = copy.deepcopy(REGISTRY)
        change({e["id"]: e for e in reg["job"]}, reg)
        return problems(found, reg)
    assert any("no registry entry" in p for p in broken(lambda e, r: r["job"].remove(e["suite/run"])))
    assert any("secrets its entry" in p for p in broken(lambda e, r: e["tick/poll"]["secrets"].remove("HC_TICK_URL")))
    assert any("permissions its entry" in p for p in broken(lambda e, r: e["tick/anchor"]["permissions"].pop()))
    assert any("model key and a write" in p for p in broken(lambda e, r: r["write_secrets"].append("TRIAGE_DB_URL")))
    assert any("no suite or no human gate" in p for p in broken(lambda e, r: r["tier"]["read"].pop("human_gate")))
    with_both = {**found, "x/y": {"secrets": {"ANTHROPIC_API_KEY"}, "permissions": {"issues: write"}, "environment": None}}
    reg = copy.deepcopy(REGISTRY)
    reg["job"].append({"id": "x/y", "owner": "o", "tier": "read", "autonomy": "read_report", "suite": "ci",
                       "secrets": ["ANTHROPIC_API_KEY"], "permissions": ["issues: write"]})
    assert any("model key and a write" in p for p in problems(with_both, reg))
    tick = (ROOT / ".github/workflows/tick.yml").read_text()
    for bad in ("      contents: read\n      # also needed\n      issues: write",  # a grant after a comment
                "      contents: read\n\n      issues: write",  # after a blank line
                '      issues: "write"',  # quoted
                "        issues: write"):  # indented deeper
        broken_tick = tick.replace("      contents: read  # checkout only", bad + "  #", 1)
        assert reads_or_refuses(broken_tick, "issues: write"), f"the reader missed the grant in {bad!r}"
    for hidden in ("${{ secrets['PREREG_SANDBOX_WRITE'] }}", "${{ toJSON(secrets) }}"):
        assert refuses(tick + f"# {hidden}\n"), f"the reader missed {hidden}"
    print(f"ok: all {len(found)} workflow jobs match the registry, each rule fires on a broken copy, and the reader"
          " fails closed")


def reads_or_refuses(text, grant):
    """True if the reader finds the poll job's grant, or refuses the file: either way nothing slips through."""
    try:
        return grant in workflow_jobs(write_tmp(text))["poll"]["permissions"]
    except AssertionError:
        return True


def refuses(text):
    try:
        workflow_jobs(write_tmp(text))
        return False
    except AssertionError:
        return True


def write_tmp(text):
    f = Path(tempfile.mkdtemp()) / "x.yml"
    f.write_text(text)
    return f


if __name__ == "__main__":
    main()
