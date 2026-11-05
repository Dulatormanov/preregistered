"""make show-bundle: before you approve a promotion run, see exactly what it will write (Build day 6).

  OBSERVER_DB_URL=... python tools/show_bundle.py
It prints the newest bundle, its exact payload, the target sandbox issue's title, and the 12 characters your
approval comment must quote. Approve only if the label is right for that issue.
"""
import json
import os
import urllib.request

import psycopg

with psycopg.connect(os.environ["OBSERVER_DB_URL"], autocommit=True) as db:
    row = db.execute("select id, day, bundle, payload, payload_sha256, exists (select from prereg.consent_claims k"
                     " where k.consent_id = c.id) from prereg.consent c order by id desc limit 1").fetchone()
if row is None:
    raise SystemExit("no bundle yet")
consent_id, day, bundle, payload, digest, claimed = row
req = urllib.request.Request(f"https://api.github.com/repos/Dulatormanov/prereg-sandbox/issues/{bundle['issue']}",
                             headers={"User-Agent": "preregistered"})
with urllib.request.urlopen(req, timeout=30) as r:
    title = json.load(r)["title"]
print(f"bundle {consent_id} of {day}{' (already used)' if claimed else ''}: {bundle['why']}")
print(f"  payload:  {payload}")
print(f"  issue:    sandbox issue {bundle['issue']}: {title}")
print(f"  label:    {bundle['label']} (the guess of {bundle['champion']})")
print(f"  approve with a comment that contains: {digest[:12]}")
