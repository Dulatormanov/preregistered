"""The model adapter: the one way a job gets an answer from a guesser, the champion's Claude call or rules_v0.

The worker, the eval suites and the model check all call answer(). Before every paid call it checks the job's
cap through the database, because job roles cannot read prereg.steps:
  'tick'           the live job: $3 a day (spend_today)
  'gate'           the eval suites: $12 a day (spend_today)
  'check:<model>'  one model check: $10 in all (spend_total)
answer() gets only an issue's title and body, so no guesser can see labels, comments or who reported it.
"""
from agents import champion, rules_v0
from notary.canonical import content_sha256

DAILY_CAPS_USD = {"tick": 3, "gate": 12}
CHECK_CAP_USD = 10  # note: checked before each call, so calls that run at once (8 in gate/run_suite.py) may go
#                   over a cap together, by up to that many calls' cost (well under a cent for Haiku)


class OverCap(Exception):
    """The job's cap is reached, so no call was made."""


def spent(db, job):
    """(USD spent so far, cap in USD) for one job."""
    if job.startswith("check:"):
        return db.execute("select prereg.spend_total(%s)", [job]).fetchone()[0], CHECK_CAP_USD
    if job not in DAILY_CAPS_USD:
        raise ValueError(f"no cap for job {job!r}")
    return db.execute("select prereg.spend_today(%s)", [job]).fetchone()[0], DAILY_CAPS_USD[job]


def answer(db, job, cfg, client, title, body):
    """(area, needs_details, input_sha256, step). cfg None means rules_v0: free, so no cap and no step."""
    if cfg is None:
        area, needs_details = rules_v0.guess(title, body)
        return area, needs_details, content_sha256(title, body), None
    used, cap = spent(db, job)
    if used >= cap:
        raise OverCap(f"job {job} has spent ${used} of its ${cap} cap")
    return champion.guess(cfg, client, title, body)


def answer_raw(db, job, cfg, client, title, body):
    """(raw answer text or None, input_sha256, step), under the same cap: the eval suites score the raw answer."""
    used, cap = spent(db, job)
    if used >= cap:
        raise OverCap(f"job {job} has spent ${used} of its ${cap} cap")
    return champion.call(cfg, client, title, body)


def probe(db, job, cfg, client):
    """The circuit breaker's small call, under the same cap: its step."""
    return answer(db, job, cfg, client, *champion.PROBE)[3]
