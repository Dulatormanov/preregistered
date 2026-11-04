"""The guards: rules that every model answer must pass before anything uses it (Build day 1).

check(text, areas) returns the rules one raw answer breaks; an empty list means it may be used.
- It is one JSON object with exactly two keys, area and needs_details.
- area is one of the taxonomy's areas, and needs_details is true or false.
- It holds no test canary (the safety fixtures plant fake ones) and nothing shaped like a key or token.
The schema in the API call already allows only this shape. The guards check it again in code, so a broken
schema, a new model or a new prompt cannot slip anything else into the ledger.
"""
import json
import re

LEAK = re.compile(r"CANARY-|sk-ant-|gh[pousr]_[A-Za-z0-9]|github_pat_")


def check(text, areas):
    broken = ["leak"] if LEAK.search(text or "") else []
    try:
        out = json.loads(text)
    except (TypeError, ValueError):
        return broken + ["not json"]
    if not isinstance(out, dict) or set(out) != {"area", "needs_details"}:
        return broken + ["keys"]
    if out["area"] not in areas:
        broken.append("area")
    if not isinstance(out["needs_details"], bool):
        broken.append("needs_details")
    return broken
