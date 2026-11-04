"""rules_v0: the free keyword floor that every model must beat.

Frozen once it has made guesses: a change is rules_v1, never an edit.
"""
import re

CHAMPION_ID = "rules_v0"
# Taxonomy v0 areas, checked in this order: the title first, then the body. No match: "other".
AREAS = (
    ("self-hosted", r"self[- ]?host|docker[- ]compose|\bkong\b"),
    ("documentation", r"\bdocs?\b|documentation|typo"),
    ("frontend", r"dashboard|studio|table editor|sql editor|\bui\b|button|website"),
    ("auth", r"\bauth|\blog ?in\b|sign ?(in|up)\b|oauth|\bjwt\b|magic link|\botp\b|\bmfa\b|\bsso\b|saml"),
    ("postgres", r"postgres|\bsql\b|\brls\b|row level security|\bpg_|extension|trigger|migration"),
)
NEEDS_DETAILS_BELOW = 200  # note: naive floor; a body this short usually lacks a reproduction


def guess(title, body):
    title, body = (title or "").lower(), (body or "").lower()
    needs_details = len(body.strip()) < NEEDS_DETAILS_BELOW
    for text in (title, body):
        for area, pattern in AREAS:
            if re.search(pattern, text):
                return area, needs_details
    return "other", needs_details
