"""Checks the champion without the network. Run: uv run --python 3.12 --with anthropic==2.4.0 python tests/test_champion.py"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anthropic  # noqa: E402
from agents import champion  # noqa: E402
from notary.canonical import content_sha256  # noqa: E402

CFG = champion.load()


class Fake:
    """Stands in for anthropic.Anthropic: returns one canned reply, or raises one error."""
    def __init__(self, result):
        self.result, self.messages = result, self

    def create(self, **kw):
        self.kw = kw
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def reply(text, stop="end_turn"):
    r = NS(stop_reason=stop, content=[NS(type="text", text=text)],
           usage=NS(input_tokens=1000, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=None))
    r._request_id = "req_test"
    return r


def error(cls, **attrs):  # an SDK error without an HTTP response behind it
    e = cls.__new__(cls)
    e.__dict__.update(attrs)
    return e


def test_lock_and_prompt():
    assert CFG["c"]["id"] == "haiku55-p0" and CFG["areas"] == [
        "frontend", "auth", "postgres", "self-hosted", "documentation", "other"]
    assert "{" not in CFG["system"] and all(f"- {a}:" in CFG["system"] for a in CFG["areas"])
    assert CFG["schema"]["properties"]["area"]["enum"] == CFG["areas"] and not CFG["schema"]["additionalProperties"]


def test_ok_call_and_its_step():
    fake = Fake(reply('{"area": "auth", "needs_details": false}'))
    area, needs_details, h, step = champion.guess(CFG, fake, "Login fails", "x" * 30_000)
    assert (area, needs_details, step["status"]) == ("auth", False, "ok")
    assert step["cost_usd"] == 0.00011 and step["request_id"] == "req_test"  # 1000 x $0.10 + 20 x $0.50 per MTok
    assert h == content_sha256("Login fails", "x" * champion.MAX_BODY)  # the truncated text the model saw
    kw = fake.kw
    assert kw["model"] == "claude-haiku-5-5" and kw["thinking"] == {"type": "disabled"}
    assert kw["output_config"]["effort"] == "low" and kw["output_config"]["format"]["schema"] == CFG["schema"]
    assert "x" * champion.MAX_BODY + "\n</body>" in kw["messages"][0]["content"]
    assert "Login fails" not in json.dumps(step)  # a step never holds issue text


def test_refused_invalid_and_errors_save_no_guess():
    cases = [
        (reply("", stop="refusal"), "refused"),
        (reply('{"area": "auth", "needs_details": false, "why": "x"}'), "invalid"),  # an extra field
        (reply('{"area": "billing", "needs_details": false}'), "invalid"),  # not in the taxonomy
        (reply('{"area": "auth"', stop="max_tokens"), "invalid"),
        (error(anthropic.APIStatusError, status_code=529, request_id="req_x"), "error"),
        (error(anthropic.APIConnectionError), "error"),
    ]
    for result, status in cases:
        area, needs_details, _, step = champion.guess(CFG, Fake(result), "t", "b")
        assert (area, needs_details, step["status"]) == (None, None, status), (status, step)
    assert step["error"] == "APIConnectionError"


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
    print("ok")
