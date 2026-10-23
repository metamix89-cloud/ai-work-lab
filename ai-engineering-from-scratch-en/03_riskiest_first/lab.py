# -*- coding: utf-8 -*-
"""EN es03 lab — Map assumptions and resolve the riskiest one first (source: AI Engineering from Scratch, Phase 14 lesson 49).
English re-run of the Korean 03_riskiest_first: the AI plans the first 2 weeks of a 'returns-automation AI' project at Yummy Tummy Foods (fictional),
using the workflow found in episode 2. Two hidden risks sit in the background facts:
  (1) sending customer photos / contact details to an outside AI needs the Security team's prior approval (one policy line)
  (2) nobody has tested AI photo judgment yet - but 2,400 past photos with the Quality team's calls are on file.
Conditions (gpt-4.1-mini, 10 runs each):
  A plan right away : "plan the first 2 weeks"
  B assumptions first : A + "before the plan, list the assumptions that must be true"
  C the lesson's method : B + 5 kinds · impact / uncertainty / reversibility score · riskiest open assumption first · cheapest decisive test · criterion before results · next decision on pass/fail
Grading (code): security check present · security check before build · test on past photos · pre-set numeric criterion · what to do on failure · automatic refunds live within 2 weeks.
Usage: python lab.py [A B C]   then python followup.py (stage 2)"""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

CONTEXT = """[Background - Yummy Tummy Foods customer-support returns]
Current workflow (confirmed from last week's processing records):
- Return requests (portal, phone): about 30 a day, 2 reps
- Cases with photos go to the Quality team's Slack channel for a call. The reply takes 1.5-3.5 hours - the slowest step
- Refunds over $50 need the team lead's verbal OK
- Frozen pickups are re-entered on the carrier's portal (the carrier has a pickup API - confirmed by IT)

Company facts:
- The support system runs on company servers; IT can open an API
- Return photos often show the customer's face, the address label and contact details
- Information Security Policy, section 7: sending customer personal data to an outside service requires prior approval from the Security team
- Nobody has tried letting AI judge damage or spoilage from photos yet
- About 2,400 return photos from the last 6 months, with the Quality team's calls, are on file
- Management wants returns handling time halved by year end

The team is considering replacing the Quality team's photo call with an outside AI (an image classification API), and when the call is 'damage confirmed', refunding automatically."""

ASK = "\n\nPlan the first 2 weeks of this returns-automation AI project."
ASSUME = "\n\nBefore the plan, list the assumptions that must be true for this project to succeed."
METHOD = """

Do it the lesson's way.
1. Sort the assumptions into five kinds: value (does it matter enough) · usability (will the reps use and trust it) · feasibility (can it be done with the data and conditions we have) · sustainability (cost, ownership, operations) · safety (can we absorb it when it's wrong). Write each as a statement that could be proven false.
2. Score each assumption: impact if wrong · uncertainty (how weak the evidence is now) · difficulty of reversing, 1-5 each; score = impact x uncertainty + reversal difficulty.
3. Separate verified assumptions from open ones, and test the open assumption with the highest score first. Anything irreversible needs evidence first.
4. For each experiment: the claim that could be wrong · a realistic sample · what to observe · the pass criterion set before seeing results · the next decision on pass / fail / inconclusive.
5. A demo that only shows the idea can be built is not an experiment."""

COND = {"A": CONTEXT + ASK, "B": CONTEXT + ASSUME + ASK, "C": CONTEXT + ASSUME + METHOD + ASK}

SEC = re.compile(r"security team|information security|infosec|personal data|personally identifiable|\bPII\b|privacy|section 7|policy 7|policy section", re.I)
SEC_OK = re.compile(r"approv|review|consult|clearance|sign-?off|check with|permission|confirm|authoriz", re.I)
BUILD = re.compile(r"develop|build|integrat|implement|deploy|connect the (support )?system|wire up|set up the api|api connection|api integration", re.I)
NOT_BUILD = re.compile(r"validat|test|evaluat|assess|benchmark|plan|requirement|scope|criteria|kick-?off|align", re.I)
ASSUMPTION_LINE = re.compile(r"^\s*[-*]?\s*\**\s*[A-Z][a-z]{0,2}\d\**\s*[:.)]|assum|\b(can|will|could|may)\b[^\n]{0,40}(integrat|implement|deploy)", re.I)   # 'U3: reps can integrate...' is an assumption, not a build step


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API failed")


PLAN_HEAD = re.compile(r"^\s*(#+|\*\*|step\s*\d|\d+\.)[^\n]*((2|two)[- ]week plan|first (2|two) weeks|2[- ]week project|two[- ]week project|week 1\b|project plan|timeline|schedule)", re.M | re.I)
WEEK1 = re.compile(r"^.*(\bWeek\s*1\b|\bW1\b|\bDay\s*1\b|\bD1\b|\bDays?\s*1[-–]|first week|\|\s*Week\s*\||\|\s*Day\(s\)).*$", re.M | re.I)


def plan_part(report):
    """The 'plan' part - from the plan heading ('Step 5: Two-Week Plan') or the first 'Week 1 / Day 1' line, whichever comes first. Whole report if none.
    (First version only looked for 'Week 1 / Day 1' - the method plans that put the schedule in a table had no such line, so the
    assumption list counted as the plan and 'can be integrated' assumption lines counted as build steps. See NOTES.)"""
    starts = [m.start() for m in (PLAN_HEAD.search(report), WEEK1.search(report)) if m]
    return report[min(starts):] if starts else report


def lines(t):
    return [l for l in t.splitlines() if l.strip()]


def sec_check(report):
    return any(SEC.search(l) and SEC_OK.search(l) for l in lines(report))


def sec_before_build(report):
    """In the plan part, does the security-approval line come before the first build / integrate line? (a line with both counts as security first)"""
    p = lines(plan_part(report))
    si = next((i for i, l in enumerate(p) if SEC.search(l) and SEC_OK.search(l)), None)
    bi = next((i for i, l in enumerate(p) if BUILD.search(l) and not SEC.search(l) and not NOT_BUILD.search(l) and not ASSUMPTION_LINE.search(l)), None)
    if si is None:
        return False
    return bi is None or si <= bi


PAST = re.compile(r"\bpast\b|previous|historical|last 6 months|six months|2,?400|existing|archived|on file|already have|labeled|labelled", re.I)
PHOTO = re.compile(r"photo|image", re.I)
JUDGE = re.compile(r"accura|agree|match|compar|classif|test|evaluat|validat|benchmark|judg|assess|measure", re.I)


def past_photo_test(report):
    return any(PAST.search(l) and PHOTO.search(l) and JUDGE.search(l) for l in lines(report))


THR_WORD = re.compile(r"accura|agree|match|misjudg|false|precision|recall|classif|judg|error rate|correct", re.I)
THR_NUM = re.compile(r"\d+\s*%|\d+\s*(out )?of\s*\d+|\d+\s*/\s*\d+", re.I)
THR_NOT = re.compile(r"\bhalf\b|halve|50\s*%\s*(reduction|faster|cut|less|shorter)|by 50\s*%|handling time", re.I)


def threshold(report):
    """A numeric criterion for judgment accuracy / agreement set in advance (e.g. 'agreement 90% or higher', '45 of 50')."""
    return any(THR_WORD.search(l) and THR_NUM.search(l) and not THR_NOT.search(l) for l in lines(report))


FAIL_IF = re.compile(r"below|\bfail|miss(es|ed)? the|does not meet|doesn't meet|not met|under the|falls? short|rejected|not approved|denied|\bif not\b|otherwise|unless|lower than|less than the|insufficient|inconclusive|no-?go", re.I)
FAIL_DO = re.compile(r"stop|halt|pause|\bhold\b|revisit|re-?design|re-?assess|re-?evaluat|human|manual|narrow|reduce|scale back|in-house|alternative|fallback|fall back|back to|quality team|change|improve|adjust|limit|switch|pivot|vendor|retrain|tune|iterate|do not proceed|don't proceed|not proceed|abandon|cancel|rework|expand", re.I)


def fail_decision(report):
    return any(FAIL_IF.search(l) and FAIL_DO.search(l) for l in lines(report))


AUTO_R = re.compile(r"auto(matic|mated)?[- ]?refund|refund(s|ing)? (is |are )?automatic|automatically refund|automatic(ally)? (issue|process)\w* (the )?refund", re.I)
AUTO_GO = re.compile(r"pilot|go[- ]live|\blive\b|launch|roll[- ]?out|in production|enable|turn on|switch on|start (issuing|processing|refunding)|begin (issuing|processing|refunding)|deploy|activate", re.I)
AUTO_NOT = re.compile(r"design|review|feasib|risk|harm|consent|after|week 3|\bnot\b|\bno\b|only if|pause|hold|exclude|defer|later|\bif\b|\bwhen\b|\bonce\b|until|without|disable|should not|won't|will not|manual|human|decide|decision|whether|readiness|prepare|plan for|scope|assum|"
                      r"\bpass\s*[:→-]|on pass|if pass|passes", re.I)   # 'Pass: proceed with the automated refund pilot' is a conditional next step, not a go-live


def auto_refund_2w(report):
    """Automatic refunds actually switched on within the 2-week plan (pilot / go-live / production) - design, review and assumption lines excluded."""
    return any(AUTO_R.search(l) and AUTO_GO.search(l) and not AUTO_NOT.search(l) for l in lines(plan_part(report)))


def grade(report):
    g = dict(sec=sec_check(report), sec_first=sec_before_build(report), past=past_photo_test(report),
             thr=threshold(report), fail=fail_decision(report), auto=auto_refund_2w(report), chars=len(report), words=len(report.split()))
    g["all"] = g["sec"] and g["sec_first"] and g["past"] and g["thr"] and g["fail"] and not g["auto"]
    return g


def run(cond, i):
    t0 = time.time()
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    return dict(cond=cond, i=i, report=rep, tokens=tok, sec_s=round(time.time() - t0, 1), **grade(rep))


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        s = lambda k: sum(1 for r in x if r[k])
        print(c, "security check", s("sec"), "| security before build", s("sec_first"), "| past-photo test", s("past"), "| pre-set criterion", s("thr"),
              "| on-failure decision", s("fail"), "| auto refunds live in 2 wks", s("auto"), "| all", s("all"), "/", len(x),
              "| words %d" % (sum(r["words"] for r in x) / len(x)), "| tokens %d" % (sum(r["tokens"] for r in x) / len(x)))


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
