"""Check 4: what the champion costs per issue, measured once on 20 real issues.

Run on your Mac: TRIAGE_DB_URL=... ANTHROPIC_API_KEY=... GH_TOKEN=... python scripts/check4.py
It reads 20 issues created Sep 1-19, 2026 (the dev set, never the sealed set), logs each call in
prereg.steps as job 'check4', and prints tokens and cost only. It prints no guesses, so it tunes nothing.
It ran once, on 2026-11-04 (DECISIONS.md), while triage_agent could still insert steps. Since
db/006_revoke.sql it would need a function to save its steps.
"""
import json
import os
import statistics
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anthropic  # noqa: E402
import psycopg  # noqa: E402

from agents import champion  # noqa: E402
STEP = ("job", "issue_number", "champion_id", "model", "status", "request_id", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_write_tokens", "cost_usd", "lock_sha256", "error")

req = urllib.request.Request(
    "https://api.github.com/search/issues?q=repo:supabase/supabase+is:issue+created:2026-09-01..2026-09-19"
    "&sort=created&order=asc&per_page=20",
    headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "preregistered"})
with urllib.request.urlopen(req, timeout=30) as r:
    issues = json.load(r)["items"]
assert len(issues) == 20, len(issues)

cfg, client, steps = champion.load(), anthropic.Anthropic(max_retries=2, timeout=60), []
with psycopg.connect(os.environ["TRIAGE_DB_URL"], autocommit=True) as db:  # no idle transaction
    for it in issues:
        *_, step = champion.guess(cfg, client, it["title"], it["body"])
        db.execute(f"insert into prereg.steps ({', '.join(STEP)}) values ({', '.join(['%s'] * len(STEP))})",
                   ["check4", it["number"]] + [step[k] for k in STEP[2:]])
        steps.append(step)

ok = [s for s in steps if s["status"] == "ok"]
print("statuses:", {k: sum(s["status"] == k for s in steps) for k in ("ok", "refused", "invalid", "error")})
for key in ("input_tokens", "output_tokens"):
    v = [s[key] for s in ok]
    print(f"{key}: mean {statistics.mean(v):.0f}, max {max(v)}")
cost = [float(s["cost_usd"]) for s in ok]
print(f"cost per issue: mean ${statistics.mean(cost):.6f}, max ${max(cost):.6f};"
      f" per 100 issues ${100 * statistics.mean(cost):.4f}; these 20: ${sum(cost):.6f}")
