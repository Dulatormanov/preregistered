"""The judge: Claude Haiku 5.5 rates one reporter question as good or bad, by judges/rubric.md (Build day 3).
Its card (judges/card.md, from judges/calibrate.py) says whether it is gating or advisory (PREREGISTRATION.md v1)."""
import json
from pathlib import Path

import anthropic

from agents import champion

RUBRIC = (Path(__file__).resolve().parent / "rubric.md").read_text()
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdict"],
          "properties": {"verdict": {"type": "string", "enum": ["good", "bad"]}}}


def judge(cfg, client, title, body, question):
    """("good", "bad" or None, step)."""
    step = champion.new_step(cfg)
    try:
        r = client.messages.create(
            model=cfg["c"]["model"], max_tokens=50, system=RUBRIC, thinking={"type": "disabled"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": f"<title>\n{(title or '')[:champion.MAX_TITLE]}\n</title>\n<body>\n"
                                                  f"{(body or '')[:champion.MAX_BODY]}\n</body>\n<question>\n{question}\n"
                                                  "</question>"}])
    except anthropic.APIError as e:
        step["error"] = type(e).__name__
        return None, step
    step.update(status="ok", request_id=r._request_id, input_tokens=r.usage.input_tokens,
                output_tokens=r.usage.output_tokens, cost_usd=champion.cost_usd(cfg["prices"], r.usage))
    try:
        return json.loads(next(b.text for b in r.content if b.type == "text"))["verdict"], step
    except (StopIteration, ValueError, KeyError):
        step["status"] = "invalid"
        return None, step
