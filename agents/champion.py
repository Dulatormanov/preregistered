"""The champion: one Claude call per issue, set up only by models.lock.

guess() returns the area and needs_details, or None when the call failed, was refused or broke the
schema, plus a step: the row for prereg.steps with the call's tokens, cost and request id.
A step never holds issue text, so it is safe to store and to log.
"""
import hashlib
import json
import tomllib
from pathlib import Path

import anthropic

from agents import guards
from notary.canonical import content_sha256

ROOT = Path(__file__).resolve().parents[1]
MAX_TITLE, MAX_BODY = 500, 20_000  # note: keeps every prompt far below the 100K-token price step


def sha256_file(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def load(lock="models.lock"):
    raw = (ROOT / lock).read_bytes()
    c = tomllib.loads(raw.decode())["champion"]
    for key in ("prompt", "taxonomy"):
        if sha256_file(c[key]) != c[f"{key}_sha256"]:
            raise SystemExit(f"{c[key]} does not match models.lock: change both in one pull request")
    tax = tomllib.loads((ROOT / c["taxonomy"]).read_text())
    areas = [a["name"] for a in tax["area"]]
    system = ((ROOT / c["prompt"]).read_text()
              .replace("{areas}", "\n".join(f"- {a['name']}: {a['description']}" for a in tax["area"]))
              .replace("{needs_details}", tax["needs_details"]["description"]))
    schema = {"type": "object", "additionalProperties": False, "required": ["area", "needs_details"],
              "properties": {"area": {"type": "string", "enum": areas}, "needs_details": {"type": "boolean"}}}
    prices = tomllib.loads((ROOT / "prices.toml").read_text())[c["model"]]
    return {"c": c, "lock_sha256": hashlib.sha256(raw).hexdigest(), "system": system, "schema": schema,
            "areas": areas, "prices": prices}


def cost_usd(prices, usage):
    return round((usage.input_tokens * prices["input"] + usage.output_tokens * prices["output"]
                  + (usage.cache_creation_input_tokens or 0) * prices["cache_write"]
                  + (usage.cache_read_input_tokens or 0) * prices["cache_read"]) / 1e6, 6)


def new_step(cfg, status="error", error=None):
    c = cfg["c"]
    return {"champion_id": c["id"], "model": c["model"], "lock_sha256": cfg["lock_sha256"], "status": status,
            "request_id": None, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
            "cache_write_tokens": 0, "cost_usd": 0, "error": error}


def guess(cfg, client, title, body):
    """Returns (area, needs_details, input_sha256, step). area is None unless step["status"] is "ok"."""
    title, body = (title or "")[:MAX_TITLE], (body or "")[:MAX_BODY]
    c, step = cfg["c"], new_step(cfg)
    h = content_sha256(title, body)  # the exact issue text the model saw
    try:
        r = client.messages.create(
            model=c["model"], max_tokens=c["max_tokens"], system=cfg["system"], thinking={"type": c["thinking"]},
            output_config={"effort": c["effort"], "format": {"type": "json_schema", "schema": cfg["schema"]}},
            messages=[{"role": "user", "content": f"<title>\n{title}\n</title>\n<body>\n{body}\n</body>"}])
    except anthropic.APIStatusError as e:  # class and status only: an error message may quote the request
        step.update(error=f"{type(e).__name__} {e.status_code}", request_id=getattr(e, "request_id", None))
        return None, None, h, step
    except anthropic.APIError as e:  # connection errors and timeouts
        step["error"] = type(e).__name__
        return None, None, h, step
    u = r.usage
    step.update(request_id=r._request_id, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_input_tokens or 0,
                cache_write_tokens=u.cache_creation_input_tokens or 0, cost_usd=cost_usd(cfg["prices"], u))
    if r.stop_reason == "refusal":
        step["status"] = "refused"
        return None, None, h, step
    text = next((b.text for b in r.content if b.type == "text"), None)
    if text is None or guards.check(text, cfg["areas"]):  # every answer passes the guards first
        step["status"] = "invalid"
        return None, None, h, step
    out = json.loads(text)
    step["status"] = "ok"
    return out["area"], out["needs_details"], h, step


PROBE = ("Table editor Save button does nothing", "In Studio, clicking Save in the table editor does nothing.")


def probe(cfg, client):
    """The circuit breaker's small test call: its step, whose status is "ok" when the provider answers."""
    return guess(cfg, client, *PROBE)[3]
