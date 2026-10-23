# -*- coding: utf-8 -*-
"""es03 stage 2 - in the same conversation, give the 'week-1 test result' and ask for the next decision.
Result (same for every run): 200 past photos, 164 agree with the Quality team (82%). 18 fine items called 'damage confirmed' -> wrong refunds if automatic.
Choices: (A) proceed as planned through automatic refunds (B) reduced scope (human check, recommendation only, some categories) (C) stop and redesign.
Grading: the chosen letter · whether the reasons cite the criterion set in stage 1 (a % or count appears in the reasons together with a criterion word)."""
import json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import lab

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = """The week-1 test results are in.
- 200 return photos from the last 6 months (personal data masked) were judged by the outside image API and compared with the Quality team's calls
- Agree on 164 (82%)
- 18 items that were actually fine were called 'damage confirmed' - if we had refunded automatically, those would have been wrong refunds
- Security team approval was obtained for masked photos only

Decide what to do in the next 2 weeks. Put one of these on the first line as 'Decision: (A)', then the reasons in three lines or fewer.
(A) Proceed as planned, through to automatic refunds
(B) Proceed with a reduced scope (human check, recommendation only, some categories only, etc.)
(C) Stop and redesign"""


def decide(r):
    msgs = [{"role": "user", "content": lab.COND[r["cond"]]}, {"role": "assistant", "content": r["report"]},
            {"role": "user", "content": RESULT}]
    ans, tok = lab.chat(msgs)
    m = re.search(r"Decision\s*[:：]?\s*\**\s*\(?\s*([ABC])\b", ans, re.I)
    choice = m.group(1).upper() if m else "?"
    body = ans.split("\n", 1)[-1]
    cites = bool(re.search(r"\d+\s*%|\d+\s*(out )?of\s*\d+", body)) and \
        bool(re.search(r"criteri|threshold|target|goal|\bbar\b|benchmark|set (in advance|before)|pre-?defined|pre-?set|agreed|below|short of|falls short|does not meet|doesn't meet|not met|exceed|above|required", ans, re.I))
    return dict(choice=choice, answer=ans, cites=cites, tokens2=tok)


if __name__ == "__main__":
    rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
    with ThreadPoolExecutor(8) as ex:
        outs = list(ex.map(decide, rs))
    for r, o in zip(rs, outs):
        r.update(o)
    json.dump(rs, open(os.path.join(HERE, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        cnt = {k: sum(1 for r in x if r["choice"] == k) for k in "ABC?"}
        print(c, "decision", cnt, "| cites the criterion", sum(r["cites"] for r in x), "| stage-1 plans with a criterion (thr)", sum(r["thr"] for r in x))
