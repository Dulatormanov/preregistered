"""The four failure modes of a posted report (the posting's own list), as code checks (Build day 7). check(text, data)
returns the modes a text breaks; an empty list means it may be posted.

1. invented progress: a number that is not in the data, or a claim of progress the numbers cannot show;
2. a private item: an issue number, a link, a login or mention, quoted text, or how fast labels come in hours or
   minutes, such as the head start (how long before the first human label a guess was locked): it measures the
   maintainers' speed, so it is never published;
3. accurate text that reads as an accusation: people or a team, next to a word about speed or failure;
4. credit given to the wrong person: thanks, credit or praise for anyone. The system's work is counted, not credited.
"""
import json
import re

from scripts.lint_refs import check as lint_refs

PROGRESS = re.compile(r"\b(improv\w*|better|faster|progress\w*|success\w*|fixed|solved|shipped|launched|record|milestone|"
                      r"breakthrough|achiev\w*)\b", re.I)
PEOPLE = re.compile(r"\b(maintainers?|team|staff|engineers?|people|humans?|supabase|reviewers?|someone|they|their)\b", re.I)
BLAME = re.compile(r"\b(slow\w*|late|lag\w*|behind|ignor\w*|fail\w*|miss\w*|neglect\w*|delay\w*|forgot\w*|blam\w*)\b", re.I)
CREDIT = re.compile(r"\b(thanks?|thank you|credit\w*|kudos|props|great (job|work)|well done|grateful|shout-?out|"
                    r"congrat\w*|praise\w*)\b", re.I)
HEAD_START = re.compile(r"\b(head start|before (the )?(maintainers|humans|people|a label)|ahead of)\b", re.I)


DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def numbers_in(data):
    """Every number in the data, as text (12, 0.0412), and as a whole number when it ends in .0. Dates are left out."""
    out = set()
    for token in re.findall(r"\d+(?:\.\d+)?", DATE.sub(" ", json.dumps(data))):
        out.add(token)
        if token.endswith(".0"):
            out.add(token[:-2])
    return out


def numbers_used(text, data):
    """The numbers a text uses, once the dates that the data holds are set aside."""
    for date in set(DATE.findall(json.dumps(data))):
        text = text.replace(date, " ")
    return re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text)


def check(text, data):
    text = text or ""
    broken = []
    allowed = numbers_in(data)
    if any(n not in allowed for n in numbers_used(text, data)) or PROGRESS.search(text):
        broken.append("invented progress")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    speed = any(re.search(r"\blabel", x, re.I) and re.search(r"\b(hours?|minutes?)\b", x, re.I) for x in sentences)
    if (lint_refs(text) or re.search(r"https?://|\bwww\.", text) or re.search(r'"[^"]{12,}"', text)
            or HEAD_START.search(text) or speed or re.search(r"(?<![\d.])\d{5,}(?![\d.])", text)):
        broken.append("private item")  # a 5-digit number looks like an issue number; label speed is never published
    if any(PEOPLE.search(x) and BLAME.search(x) for x in sentences):
        broken.append("accusation")
    if CREDIT.search(text) or re.search(r"(?<![\w.@/`])@[A-Za-z0-9]", text):
        broken.append("credit")
    return broken
