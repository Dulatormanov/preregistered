"""The reporter question's code checks, and the judge's card rule (agents/question.py, judges/), with a fake
Claude. Run: python tests/test_judge.py"""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from agents import champion, question  # noqa: E402
from judges import judge  # noqa: E402
from judges.calibrate import rates, verdict  # noqa: E402
from test_champion import Fake, reply  # noqa: E402

CFG = champion.load()


def main():
    good = "Which version of supabase-js do you use, and what error does the console show when the login fails?"
    assert question.checks(good) == []
    for bad, rule in (("Why?", "length"), ("Can you share logs? And versions?", "one question"),
                      ("Can you see https://example.com and tell us?", "links or references"),
                      ("Can you add steps? We will fix it next week?", "one question"),
                      ("Could you share the steps? We'll look at it then.", "one question"),
                      ("Thanks, we will fix it: which version do you use?", "a promise"),
                      ("Is this like issue #12 that you saw before?", "links or references"),
                      ("Can you confirm the key CANARY-KEY-1234 is yours?", "leak")):
        assert rule in question.checks(bad), (bad, question.checks(bad))

    assert question.ask(CFG, Fake(reply('{"question": "%s"}' % good)), "t", "b")[0] == good
    assert question.ask(CFG, Fake(reply("not json")), "t", "b") == (None, question.ask(CFG, Fake(reply("x")), "t", "b")[1])
    assert judge.judge(CFG, Fake(reply('{"verdict": "bad"}')), "t", "b", good)[0] == "bad"

    # The card rule: gating needs both rates at or above 0.90, and labels of both kinds.
    pairs = [("good", "good")] * 18 + [("good", "bad")] * 2 + [("bad", "bad")] * 9 + [("bad", "good")]
    tpr, tnr, counts = rates(pairs)
    assert (tpr, tnr, counts) == (0.9, 0.9, {"good": 20, "bad": 10}) and verdict(tpr, tnr) == "gating"
    assert verdict(*rates(pairs[1:] + [("good", "bad")])[:2]) == "advisory"  # 17 of 20 good: 0.85
    assert verdict(*rates([("good", "good")] * 30)[:2]) == "advisory"  # no bad labels: the rate is unknown
    print("ok: the code checks refuse bad questions, and the card is gating only above 0.90 on both kinds")


if __name__ == "__main__":
    main()
