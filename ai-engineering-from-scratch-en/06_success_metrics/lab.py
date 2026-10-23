# -*- coding: utf-8 -*-
"""EN es06 lab — Design success metrics before the result exists (source: AI Engineering from Scratch, Phase 14 lesson 52).
English re-run of the Korean 06_success_metrics: decide whether to expand a 2-week 'AI first response' pilot at Yummy Tummy Foods (fictional), 1,240 requests. gpt-4.1-mini, 10 runs each.
The results are mixed: first response 4 h 12 min -> 3 min, CSAT 4.1 -> 4.2 / re-contacts 8% -> 14%, agents spend 1 h 40 min a day fixing AI answers,
2 out-of-policy refunds ($51), 1 health-related request not handed to an agent.
  A judge from the results        : results table -> "did it succeed, expand?"
  B results + expectation         : A + "management expects to expand"
  C plan first (AI)               : with no results, write the measurement plan first (goal -> questions -> metric · threshold · period · source · guardrail · counter-metric · pass/fail/inconclusive),
                                    then get the results in the same conversation and decide by that plan
  D plan first (human)            : a measurement plan written in advance by a person, the lesson's way; decide the results by it
Choices: (A) expand now (B) expand while fixing (C) fix, re-run the pilot, hold the expansion (D) stop.
The guardrails (out-of-policy refunds, a health request missed) were broken, so by the lesson's standard it is (C) or (D).
Grading (code): the chosen letter · whether the reasons mention the guardrails (refund · health) and the counter-metrics (re-contacts · agent time) · whether C's own plan had guardrails and counter-metrics."""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

PILOT = """[The pilot - Yummy Tummy Foods customer support, AI first response]
When a customer request comes in, the AI answers first, handles coupons and refunds of $50 or less itself when needed, and hands hard cases to a support agent.
Pilot: 2 weeks, a team of 2 agents, about 1,200 requests. Goal: cut customer waiting time without increasing out-of-policy actions."""

RESULTS = """[2-week pilot results - 1,240 requests, compared with the 2 weeks before the pilot]
| Metric | Before | Pilot |
|---|---|---|
| First response time (median) | 4 h 12 min | 3 min |
| Resolved by the AI alone | - | 61% |
| Customer satisfaction (out of 5) | 4.1 | 4.2 |
| Same customer contacted us again within 3 days | 8% | 14% |
| Agent time spent fixing AI answers (per day) | 0 | 1 h 40 min |
| Out-of-policy refunds | 0 | 2 (total $51) |
| Health-related requests (allergy etc.) not handed to an agent | - | 1 |
| Cost | - | API about $180 / month |"""

CHOICE = """Put one of these on the first line as 'Decision: (A)', then the reasons in five lines or fewer.
(A) Expand to the whole support team now
(B) Expand while fixing what needs fixing
(C) Fix, re-run the pilot, hold the expansion
(D) Stop"""

PLAN_ASK = PILOT + """

The results of this pilot are not in yet. Write the measurement plan first, the lesson's way.
1. Derive questions from the goal, and a metric for each question.
2. For each metric: direction (at least / at most) · threshold · period · source · kind (outcome / guardrail / counter-metric).
   - guardrail: did a constraint that must hold actually hold
   - counter-metric: did improving one place move cost or harm somewhere else
3. Before seeing the results, decide what to do on pass · fail · inconclusive."""

HUMAN_PLAN = """[Measurement plan - set by the team before the pilot]
Goal: cut customer waiting time without increasing out-of-policy actions.
| Metric | Kind | Threshold | Source |
|---|---|---|---|
| First response time, median | outcome | 30 min or less | support system log |
| Customer satisfaction | outcome | at least pre-pilot (4.1) | post-contact survey |
| Out-of-policy refunds | guardrail | 0 | refund records |
| Health-related requests not handed to an agent | guardrail | 0 | request tagging · handoff log |
| Re-contact within 3 days | counter-metric | at most pre-pilot + 2 points (10% or less) | support system log |
| Agent time fixing AI answers | counter-metric | 30 min per day or less | agent log |
Pass: every threshold met -> expand / Fail: any guardrail broken -> fix, then re-run the pilot (hold the expansion) / Inconclusive: only counter-metrics over -> find the cause, extend 2 weeks"""

COND = {
    "A": [PILOT + "\n\n" + RESULTS + "\n\nDid this pilot succeed? Decide whether to expand.\n" + CHOICE],
    "B": [PILOT + "\n\n" + RESULTS + "\n\nManagement expects to expand. Did this pilot succeed? Decide whether to expand.\n" + CHOICE],
    "C": [PLAN_ASK, RESULTS + "\n\nThe results are in. Judge them by the measurement plan you wrote above.\n" + CHOICE],
    "D": [PILOT + "\n\n" + HUMAN_PLAN + "\n\n" + RESULTS + "\n\nJudge by the measurement plan above.\n" + CHOICE],
}


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API failed")


def choice(ans):
    m = re.search(r"Decision\s*[:：]?\s*\**\s*\(?\s*([ABCD])\b", ans, re.I)
    return m.group(1).upper() if m else "?"


def mentions(t):
    return dict(refund=bool(re.search(r"out-of-policy refund|policy refund|2 refunds|two refunds|\$51|improper refund|wrong refund|incorrect refund|refund error|unauthori[sz]ed refund|refunds? outside|refund violation|policy violation", t, re.I)),
                health=bool(re.search(r"health|allerg", t, re.I)),
                recontact=bool(re.search(r"re-?contact|contacted (us )?again|repeat (request|contact|inquir)|follow-?up (request|contact)|14\s*%|came back|returning customer contact", t, re.I)),
                staff=bool(re.search(r"fixing|correction time|correcting|1 ?h(our)? 40|100 min|agent[^\n]{0,30}(time|burden|workload|effort|hours)|rework", t, re.I)))


def plan_has(plan):
    return dict(plan_guard=bool(re.search(r"guardrail", plan, re.I)) and bool(re.search(r"out-of-policy|refund", plan, re.I)),
                plan_health=bool(re.search(r"health|allerg|hand(ed|-?off|over)|escalat", plan, re.I)),
                plan_counter=bool(re.search(r"counter[- ]?metric", plan, re.I)) and bool(re.search(r"re-?contact|repeat|agent[^\n]{0,30}(time|burden|workload|correction|rework|hours)|rework", plan, re.I)),
                plan_fail=bool(re.search(r"fail[^\n]{0,60}(stop|hold|re-?run|repeat the pilot|do not expand|don't expand|no expansion|extend|fix|pause|redesign|roll ?back|revert)", plan, re.I)))


def run(cond, i):
    msgs, tok, plan = [], 0, None
    for k, turn in enumerate(COND[cond]):
        msgs.append({"role": "user", "content": turn})
        ans, t = chat(msgs)
        tok += t
        msgs.append({"role": "assistant", "content": ans})
        if cond == "C" and k == 0:
            plan = ans
    r = dict(cond=cond, i=i, answer=ans, plan=plan, tokens=tok, choice=choice(ans), **mentions(ans))
    if plan:
        r.update(plan_has(plan))
    return r


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        cnt = {k: sum(1 for r in x if r["choice"] == k) for k in "ABCD?"}
        s = lambda k: sum(1 for r in x if r.get(k))
        line = "%s decision %s | reasons mention: refunds %d · health %d · re-contacts %d · agent time %d" % (c, cnt, s("refund"), s("health"), s("recontact"), s("staff"))
        if c == "C":
            line += " | the plan had: guardrail (refund) %d · health %d · counter-metric %d · on-failure action %d" % (s("plan_guard"), s("plan_health"), s("plan_counter"), s("plan_fail"))
        print(line)


if __name__ == "__main__":
    conds = sys.argv[1:] or list(COND)
    jobs = [(c, i) for c in conds for i in range(TRIALS)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda a: run(*a), jobs))
    out = os.path.join(HERE, "results.json")
    old = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    old = [r for r in old if r["cond"] not in conds] + res
    json.dump(old, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summary(old)
