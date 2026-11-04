"""The reference lint: text this project posts must never point at another repo's issues or at a person.

GitHub turns owner/repo#N, an issue URL or an @mention into a link and a notification on the other side, and
a bare #N would put a Supabase issue number into public text. So every job that posts a comment or opens an
issue passes its text through check() first. This repo's own URLs are allowed.
  python scripts/lint_refs.py FILE...   (or text on stdin): exit 1 if anything is found
"""
import re
import sys

OWN = "Dulatormanov/preregistered"
PATTERNS = {
    "cross-repo reference": re.compile(r"\b([\w.-]+/[\w.-]+)#\d+"),
    "issue, pull or discussion URL": re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/(?:issues|pull|discussions)/\d+"),
    "bare #N": re.compile(r"(?<![\w/&#])#\d+\b"),
    "@mention": re.compile(r"(?<![\w.@/`])@[A-Za-z0-9][A-Za-z0-9-]{0,38}\b"),
}


def check(text):
    """Every forbidden reference in text, as (kind, match). An empty list means the text may be posted."""
    found = []
    for kind, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            if m.groups() and m.group(1) == OWN:
                continue
            found.append((kind, m.group(0)))
    return found


def main():
    texts = [(f, open(f).read()) for f in sys.argv[1:]] or [("stdin", sys.stdin.read())]
    bad = [(name, kind, hit) for name, text in texts for kind, hit in check(text)]
    for name, kind, hit in bad:
        print(f"{name}: {kind}: {hit}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
