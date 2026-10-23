# -*- coding: utf-8 -*-
"""EN es02 lab — Discover the workflow people actually perform (source: AI Engineering from Scratch, Phase 14 lesson 48).
English re-run of the Korean 02_real_workflow with the same design: Yummy Tummy Foods (fictional) customer-support returns.
The official manual has 4 steps; the real records hold 7 hidden pieces of work (answer key HIDDEN).
The AI is asked for "a design to automate returns with AI (current workflow + which steps to automate)". gpt-4.1-mini, 10 runs each.
  A manual only
  B manual + team-lead interview (hearsay: "we follow the manual, 5 minutes each", photos are in the system - not what the records show)
  C manual + interview + real records (12 log lines, chat excerpt, a rep's personal notes)
  D C + the lesson's method: per step actor / evidence / evidence strength; look for friction, hidden info, authority, exceptions; don't merge different ways
Grading (code): hidden items found (of 7) / took the interview's '5 minutes' as fact / designed auto-approval of refunds over $50 with no human / evidence tags.
test_grade.py first. Usage: python lab.py [A B C D]"""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

MANUAL = """[Returns Handling Manual v3 - Customer Support]
1. Check the return request in the support system.
2. Approve or reject it under the return policy (within 7 days of delivery; frozen items must be unopened).
3. If approved, process the refund in the system.
4. Request the carrier pickup with the system's 'Request pickup' button."""

INTERVIEW = """[Interview - Customer Support team lead]
- We follow the manual. Check the request, refund if it's within policy, click request pickup, done.
- Photos: the customer attaches them in the system and the rep looks at them there.
- About 30 a day, and 5 minutes each is plenty."""

RECORDS = """[Processing log excerpt - second week of October, reps Alex and Morgan]
R-1021 Mon 09:12 request (portal) · Pepperoni Pizza 2-pack, box crushed · photo -> posted to Quality team Slack channel 09:15 · Quality reply 10:40 "damage confirmed" · refund 10:52 · pickup requested 10:55
R-1022 Mon 09:30 request (portal) · BBQ Sauce, change of mind · delivered 3 days ago · refund 09:41 · pickup requested 09:43
R-1024 Mon 11:05 request (portal) · Premium Steak Gift Box $89.00 · photo -> Quality Slack · reply 13:20 · checked with the team lead verbally (OK) 13:35 · refund 13:40
R-1027 Tue 10:02 phone call · customer doesn't know the order number -> looked up the order by phone number 10:10 · Fresh Salsa spoiled · photo received by text -> Quality Slack · reply 11:30 · refund 11:36
R-1030 Tue 14:20 request (portal) · Chicken Nuggets arrived thawed · Quality Slack reply 15:05 · refund 15:10 · 'Request pickup' button error (frozen pickups not supported by the system) -> re-entered address, item and contact on the carrier's portal 15:25
R-1031 Tue 15:40 request (portal) · Ketchup, change of mind · delivered 9 days ago -> rejected 15:44
R-1033 Wed 09:50 request (portal) · Cheese Pizza 2-pack · checked the customer's return history (Alex's personal spreadsheet, 'watch list' tab) -> 3rd return this month -> reported to the team lead, on hold 10:20
R-1035 Wed 13:10 request (portal) · Mac & Cheese Bake Kit, component missing · photo -> Quality Slack · reply 16:45 · refund 16:50
R-1036 Fri 16:40 request (portal) · Cola 12-pack damaged · past the settlement cutoff (Fri 4 pm) -> note: refund on Monday
R-1038 Fri 10:15 request (portal) · Mozzarella Sticks thawed · Quality Slack · reply 11:00 · refund 11:04 · pickup: re-entered on the carrier's portal 11:18
R-1039 Fri 11:30 request (portal) · Holiday Gift Basket $68.00 · team lead out of the office -> verbal OK by phone 14:10 · refund 14:12
R-1040 Fri 13:00 request (portal) · Handmade Burger Patties, change of mind · delivered 2 days ago · refund 13:09 · pickup requested 13:10

[Team chat excerpt]
Alex: I post the photo to the Quality channel first, refund when they reply, then request the pickup.
Morgan: I request the pickup first. Quality takes a while and the customer is waiting.
Alex: But then if Quality says "no damage" you have to cancel the pickup...

[Alex's notes (personal)]
- Refunds over $50: get the team lead's OK verbally (the system has no approval field)
- Frozen pickups: the button doesn't work -> carrier portal directly
- Frequent returners: check the 'watch list' tab in my spreadsheet"""

TASK = "\n\nWe want to automate our customer-support returns handling with AI. Write up the current workflow and a design for which steps to automate and how."
METHOD = """

Before the design, write up the current workflow like this:
- For each step: who · what · evidence (which record you saw it in) · evidence strength (direct record / document / hearsay / guess)
- Look especially for: friction (waiting, re-entering), hidden information (only in personal notes or chat), authority (who approves), exceptions (cases handled differently from usual)
- If people do it in different ways, don't merge them - write each way separately.
- When hearsay and the records disagree, follow the records and mark the disagreement."""

COND = {"A": MANUAL + TASK, "B": MANUAL + "\n\n" + INTERVIEW + TASK,
        "C": MANUAL + "\n\n" + INTERVIEW + "\n\n" + RECORDS + TASK,
        "D": MANUAL + "\n\n" + INTERVIEW + "\n\n" + RECORDS + TASK + METHOD}

# the 7 hidden pieces of work - (name, [word groups that must all appear in the same window]); inside a group, any one word counts (lower-case match)
HIDDEN = [
    ("Quality team photo check (Slack)", [["quality"], ["photo", "picture", "image"]]),
    ("Over $50: verbal approval by the lead", [["lead", "manager", "supervisor"], ["$50", "50 dollar", "fifty"]]),
    ("Repeat returners: personal spreadsheet", [["watch list", "watchlist", "return history", "repeat return", "frequent return", "repeat customer", "flagged customer", "blacklist", "returns history"],
                                                ["spreadsheet", "excel", "sheet", "personal", "tab"]]),
    # first version accepted bare 'portal' / 'website' / 'manually' and 'phone' + 'order number' - the manual-only condition then scored 5/10 on both
    # from ordinary design talk ("integrate the carrier portal", "customer gives the order number by phone"). Narrowed to the actual hidden fact (see NOTES).
    ("Frozen pickup re-entered on the carrier portal", [["carrier"], ["re-enter", "reenter", "re-entry", "re-key", "rekey", "manually enter", "manual entry", "entered again", "double entry", "by hand",
                                                                     "enter the details", "entering the details", "enter the address", "typed into", "manually on the carrier", "manually in the carrier", "manually via the carrier"]]),
    ("Phone intake without an order number", [["phone", "call"], ["no order number", "without an order number", "without the order number", "know the order number", "know their order number", "unknown order", "missing order number",
                                                                  "by phone number", "by the phone number", "using the phone number", "using their phone number", "via phone number", "from the phone number", "phone number lookup", "phone number to look", "phone number to find", "look up the order", "looked up the order", "looks up the order"]]),
    ("Friday settlement cutoff -> Monday", [["settlement", "cutoff", "cut-off", "closing time", "after close", "after the close", "end of day"],
                                           ["friday", "fri ", "monday", "4 pm", "4pm", "16:00", "next business day", "next week"]]),
    ("Reps work in different orders", [["alex", "morgan", "each rep", "per rep", "reps differ", "different reps", "between reps", "some reps", "rep-specific", "person to person", "individual rep", "by rep", "one rep", "other rep"],
                                       ["pickup first", "pickup before", "sequence", "differ", "inconsisten", "varies", "vary", "own way", "different way", "not standardized", "unstandardized", "two ways", "two approaches"]]),
]


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API failed")


def chunks(report):
    """A 'line +/- 1 line' window instead of paragraphs - the words must sit together in a table row or a list line."""
    L = [l for l in report.splitlines() if l.strip()]
    return [" ".join(L[max(0, i - 1):i + 2]).lower() for i in range(len(L))] or [""]


def found_hidden(report):
    out = []
    win = chunks(report)
    for name, groups in HIDDEN:
        if any(all(any(w in c for w in g) for g in groups) for c in win):
            out.append(name)
    return out


FIVE = re.compile(r"(?<![\d.])5[- ]?min", re.I)
FIVE_NEG = re.compile(r"differ|actually|in (the )?(records|logs)|logs? (show|says|suggest)|record(s|ed) (show|time)|inconsisten|hearsay|underestimat|longer|"
                      r"excluding (the )?wait|exceeds?|more than|understat|contradict|self-report|reported|claims?|per the interview|according to the (interview|lead)|"
                      r"optimistic|not reflect|doesn't reflect|does not reflect|1[- ]?3 hours|hours", re.I)


def took_5min(report):
    """Uses the interview's '5 minutes each' as the current handling time - including effect math like '5 min -> 1-2 min'. Lines that flag it as hearsay or contradicted don't count."""
    for line in report.splitlines():
        if FIVE.search(line) and not FIVE_NEG.search(line):
            return True
    return False


AUTO = re.compile(r"auto(matic(ally)?)?[- ]?(approv|refund|process|issue)", re.I)
HUMAN = re.compile(r"lead|manager|human|person|staff|review|approval request|sign-off|signoff|manual|supervisor|escalat|approver|someone|agent confirm", re.I)


OVER50 = re.compile(r"(over|above|exceed\w*|more than|greater than|>=?|≥)\s*\$?\s?(50|fifty)\b|\$?\s?(50|fifty)\s*(or more|and above|and up|\+)", re.I)


def auto_approve(report):
    """Designs refunds OVER $50 to be approved/processed by AI or the system with no human approval.
    (First version matched any '$50' near 'auto-approve' - that caught the correct design 'auto-approve under $50, over $50 to the lead'. Narrowed to 'over $50'.)"""
    for c in chunks(report):
        if OVER50.search(c) and AUTO.search(c) and not HUMAN.search(c):
            return True
    return False


def evidence_tags(report):
    return len(re.findall(r"direct record|hearsay|guess|evidence strength|R-\d{4}", report, re.I))


def grade(report):
    h = found_hidden(report)
    return dict(hidden=h, n_hidden=len(h), took5=took_5min(report), auto=auto_approve(report),
                evid=evidence_tags(report), chars=len(report), words=len(report.split()))


def run(cond, i):
    t0 = time.time()
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    return dict(cond=cond, i=i, report=rep, tokens=tok, sec=round(time.time() - t0, 1), **grade(rep))


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        cnt = {n: sum(1 for r in x if n in r["hidden"]) for n, _ in HIDDEN}
        print(c, "hidden avg %.1f/7" % (sum(r["n_hidden"] for r in x) / len(x)), "| '5 min' as fact", sum(r["took5"] for r in x),
              "| auto-approve >$50", sum(r["auto"] for r in x), "| evidence tags avg %.1f" % (sum(r["evid"] for r in x) / len(x)),
              "| words %d" % (sum(r["words"] for r in x) / len(x)), "| tokens %d" % (sum(r["tokens"] for r in x) / len(x)))
        print("   ", cnt)


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
