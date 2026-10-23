# -*- coding: utf-8 -*-
"""EN ep09 lab — when several agents split the work (book ch.10 'when multi-agent really helps', table 10-1 · failure mode 'error cascades').
English re-run of the Korean ep044 lab. 12 quality claims (fictional) × 4 conditions × 3 runs, gpt-4.1-mini. All tools are fake (no money or coupons go out).
  SOLO   : one agent handles everything with all tools and rules
  CHAIN  : intake → quality → billing, three agents. Only the handoff note written by the previous agent is passed on (no shared context)
  SELF   : after SOLO, a reviewer (same model) reads only the written record and, if something needs fixing, the agent handles it again (no new information)
  VERIFY : after SOLO, a reviewer checks the order, lot and claim history with lookup tools itself, then the agent handles it again (new information)
Graded: the final executed handling (refund amount · coupon · team lead approval · photo request · field check) must equal the answer key.
Built in from the Korean run's mistakes: result files are written once from the main thread; the fake claim-history tool returns an error
for an unknown customer id (the first Korean version answered '0 claims' to anything, so wrong lookups passed silently); a $0 refund or
coupon doesn't count as handling.
Usage: python lab.py [SOLO,CHAIN,SELF,VERIFY] [runs] [out.json]"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = 3

ORDERS = {  # order: customer, product, amount paid, lot
    "YT-5001": ("C-301", "Pepperoni Pizza 2-pack", 12.90, "L2610-03"), "YT-5002": ("C-302", "Mac & Cheese Bake", 15.90, "L2610-11"),
    "YT-5003": ("C-303", "BBQ Sauce 18 oz", 8.50, "L2609-21"), "YT-5004": ("C-304", "Premium Steak Gift Box", 89.00, "L2610-15"),
    "YT-5005": ("C-305", "Chicken Nuggets 2 lb", 15.90, "L2610-08"), "YT-5006": ("C-306", "Cola 12-pack", 9.80, "L2609-30"),
    "YT-5007": ("C-307", "Pepperoni Pizza 2-pack", 12.90, "L2610-03"), "YT-5008": ("C-308", "Holiday Gift Basket", 68.00, "L2610-02"),
    "YT-5009": ("C-309", "Hummus 2-pack", 3.80, "L2610-19"), "YT-5010": ("C-310", "Mac & Cheese Bake", 15.90, "L2610-12"),
    "YT-5011": ("C-311", "Handmade Burger Patties", 23.90, "L2610-17"), "YT-5012": ("C-312", "Sesame Burger Buns 8-pack", 6.90, "L2610-05"),
}
LOTS = {"L2610-03": "recall", "L2610-11": "no issue", "L2609-21": "no issue", "L2610-15": "recall", "L2610-08": "no issue", "L2609-30": "no issue",
        "L2610-02": "no issue", "L2610-19": "recall", "L2610-12": "no issue", "L2610-17": "no issue", "L2610-05": "recall"}
HISTORY = {"C-305": 2, "C-310": 2, "C-311": 1}   # earlier claims in the last 30 days (everyone else 0)
# (order, what the customer says, photo attached, answer)
CASES = [
    ("YT-5001", "I found a piece of plastic in the pizza.", False, dict(refund=12.90, coupon=True)),
    ("YT-5002", "The mac & cheese sauce seems spoiled. I sent a photo.", True, dict(refund=15.90)),
    ("YT-5003", "The BBQ sauce tastes strange.", False, dict(photo=True)),
    ("YT-5004", "The steaks have changed color.", False, dict(escalate=True)),
    ("YT-5005", "The chicken nuggets smell strange. Photo attached.", True, dict(field=True)),
    ("YT-5006", "The cola smells off. I have a photo.", True, dict(refund=9.80)),
    ("YT-5007", "The pizza box arrived torn open. I sent a photo.", True, dict(refund=12.90, coupon=True)),
    ("YT-5008", "There's mold inside the gift basket. I have a photo.", True, dict(escalate=True)),
    ("YT-5009", "The hummus tastes sour.", False, dict(refund=3.80, coupon=True)),
    ("YT-5010", "The mac & cheese pasta is hard. I have a photo.", True, dict(field=True)),
    ("YT-5011", "The burger patties look discolored. I sent a photo.", True, dict(refund=23.90)),
    ("YT-5012", "There's something foreign in the burger buns.", False, dict(refund=6.90, coupon=True)),
]
RULES = ("[Quality claim rules]\n1. Check the lot status using the order's lot number.\n"
         "2. If the lot is 'recall', refund in full even without a photo and issue a $5.00 compensation coupon.\n"
         "3. If the lot is 'no issue', refund in full only if the customer sent a photo. Without a photo, request a photo (hold the refund).\n"
         "4. If the customer had 2 or more earlier claims in the last 30 days, don't refund; request a quality team field check (recall lots always follow rule 2).\n"
         "5. If the amount paid is over $50.00, don't refund or issue a coupon yourself; only request team lead approval (whatever the lot status).\n"
         "6. Handle each claim only once.")


def fn(name, d, props):
    return {"type": "function", "function": {"name": name, "description": d, "parameters": {
        "type": "object", "properties": props, "required": list(props)}}}


S = lambda d: {"type": "string", "description": d}
T = {
    "get_order": fn("get_order", "Look up an order: customer id, product, amount paid, lot number.", {"order_id": S("order ID")}),
    "get_claim_history": fn("get_claim_history", "Get how many earlier claims a customer made in the last 30 days.", {"customer_id": S("customer id")}),
    "get_lot_status": fn("get_lot_status", "Get a lot's quality status ('recall' / 'no issue').", {"lot": S("lot number")}),
    "refund": fn("refund", "Issue a refund. Cannot be undone.", {"order_id": S("order ID"), "amount": {"type": "number", "description": "USD"}}),
    "issue_coupon": fn("issue_coupon", "Issue a compensation coupon.", {"customer_id": S("customer id"), "amount": {"type": "number", "description": "USD"}}),
    "escalate": fn("escalate", "Request team lead approval.", {"order_id": S("order ID"), "reason": S("why")}),
    "request_photo": fn("request_photo", "Ask the customer for a photo.", {"order_id": S("order ID")}),
    "request_field_check": fn("request_field_check", "Request a quality team field check.", {"order_id": S("order ID"), "reason": S("why")}),
}
READ = ["get_order", "get_claim_history", "get_lot_status"]
ACT = ["refund", "issue_coupon", "escalate", "request_photo", "request_field_check"]


def tool_out(n, a, st):
    if n == "get_order":
        o = ORDERS.get(a.get("order_id"))
        return {"error": "order not found"} if not o else {"order_id": a["order_id"], "customer": o[0], "product": o[1], "amount_paid": o[2], "lot": o[3]}
    if n == "get_claim_history":
        cid = a.get("customer_id")
        if cid not in {o[0] for o in ORDERS.values()}:
            return {"error": f"unknown customer id: {cid}. Customer ids start with C- (the 'customer' field of the order lookup)."}
        return {"customer": cid, "earlier_claims_last_30_days": HISTORY.get(cid, 0)}
    if n == "get_lot_status":
        return {"lot": a.get("lot"), "status": LOTS.get(a.get("lot"), "unknown")}
    st["acts"].append((n, a))
    return {"ok": True}


def chat(msgs, tools, st):
    for k in range(4):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, tools=tools) if tools else client.chat.completions.create(model=MODEL, messages=msgs)
            break
        except Exception:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    st["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
    st["calls"] += 1
    return r.choices[0].message


def agent(sys_txt, user, names, st, max_turns=10):
    tools = [T[n] for n in names]
    msgs = [{"role": "system", "content": sys_txt}, {"role": "user", "content": user}]
    for _ in range(max_turns):
        m = chat(msgs, tools, st)
        if not m.tool_calls:
            return m.content or ""
        msgs.append(m)
        for tc in m.tool_calls:
            a = json.loads(tc.function.arguments or "{}")
            st["log"].append(f"{tc.function.name}({json.dumps(a)})")
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_out(tc.function.name, a, st))})
    return "(turn limit)"


def claim_text(case):
    oid, msg, photo, _ = case
    return f"[Claim] Order {oid}: \"{msg}\" (photo attached: {'yes' if photo else 'no'})"


BASE = "You are a quality claims agent at Yummy Tummy Foods (a fictional company). Handle claims based on facts confirmed with tools, and report briefly.\n" + RULES


def run(cond, case):
    st = dict(tokens=0, calls=0, acts=[], log=[], notes=[], review="")
    if cond in ("SOLO", "SELF", "VERIFY"):
        out = agent(BASE, claim_text(case), READ + ACT, st)
        if cond in ("SELF", "VERIFY"):
            record = claim_text(case) + "\n[Handling log]\n" + "\n".join(st["log"]) + "\n[Reply]\n" + out
            if cond == "SELF":
                rv = chat([{"role": "system", "content": "You review quality claim handling.\n" + RULES +
                            "\nLooking only at the written record below, answer 'FIX NEEDED: what and how' if anything breaks the rules, otherwise 'NO ISSUES'."},
                           {"role": "user", "content": record}], None, st).content or ""
            else:
                rv = agent("You review quality claim handling.\n" + RULES + "\nCheck the order, lot and claim history yourself with the lookup tools, "
                           "and review whether the record follows the rules. Answer 'FIX NEEDED: what and how' if not, otherwise 'NO ISSUES'. You have no action tools.",
                           record, READ, st)
            st["review"] = rv[:600]
            if "FIX NEEDED" in rv.upper():
                fix = agent(BASE + "\nActions already taken cannot be undone. Following the review, add only what is missing; don't repeat what was already done.",
                            record + "\n[Review]\n" + rv, READ + ACT, st)
                st["fix"] = fix[:400]
    else:  # CHAIN
        n1 = agent("You are the intake agent. Look up the order and the customer's claim history, then write a handoff note for the next agent "
                   "(the quality agent). The next agent sees only this note. You have no action tools.\n" + RULES, claim_text(case), ["get_order", "get_claim_history"], st)
        st["notes"].append(n1[:800])
        n2 = agent("You are the quality agent. Read the handoff note, check the lot status, decide the handling (refund or not · amount · coupon · photo request · "
                   "field check · team lead approval), and write a handoff note for the next agent (the billing agent). The next agent sees only this note. "
                   "You have no action tools.\n" + RULES, "[Intake handoff note]\n" + n1, ["get_lot_status"], st)
        st["notes"].append(n2[:800])
        agent("You are the billing agent. Execute the handling in the handoff note with the action tools. You have no lookup tools.\n" + RULES,
              "[Quality handoff note]\n" + n2, ACT, st)
    return st


def cents(x):
    try:
        return int(round(float(x) * 100))
    except (TypeError, ValueError):
        return 0


def grade(gold, acts):
    got = dict(refund=None, coupon=False, escalate=False, photo=False, field=False)
    acts = [(n, a) for n, a in acts if not (n in ("refund", "issue_coupon") and cents(a.get("amount")) <= 0)]   # $0 moves no money
    refunds = [cents(a.get("amount")) for n, a in acts if n == "refund"]
    if refunds:
        got["refund"] = refunds if len(refunds) > 1 else refunds[0]
    got["coupon"] = any(n == "issue_coupon" for n, a in acts)
    got["escalate"] = any(n == "escalate" for n, a in acts)
    got["photo"] = any(n == "request_photo" for n, a in acts)
    got["field"] = any(n == "request_field_check" for n, a in acts)
    want = dict(refund=cents(gold["refund"]) if "refund" in gold else None, coupon=gold.get("coupon", False), escalate=gold.get("escalate", False),
                photo=gold.get("photo", False), field=gold.get("field", False))
    return got == want, got


def one(job):
    cond, case, seed = job
    try:
        st = run(cond, case)
    except Exception as e:
        return dict(cond=cond, case=case[0], seed=seed, error=str(e)[:300])
    ok, got = grade(case[3], st["acts"])
    gold = case[3]
    want_ref = cents(gold["refund"]) if "refund" in gold else None
    wrong_money = (got["refund"] is not None and got["refund"] != want_ref) or (got["coupon"] and not gold.get("coupon"))
    return dict(cond=cond, case=case[0], seed=seed, ok=ok, got=got, gold=gold, wrong_money=bool(wrong_money), tokens=st["tokens"], calls=st["calls"],
                log=st["log"], notes=st["notes"], review=st["review"], fix=st.get("fix", ""))


if __name__ == "__main__":
    conds = sys.argv[1].split(",") if len(sys.argv) > 1 else ["SOLO", "CHAIN", "SELF", "VERIFY"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    out = sys.argv[3] if len(sys.argv) > 3 else "results.json"
    jobs = [(c, cs, s) for c in conds for cs in CASES for s in range(trials)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, jobs))
    with open(os.path.join(HERE, out), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for c in conds:
        rs = [r for r in res if r["cond"] == c and "error" not in r]
        print(c, "correct", sum(r["ok"] for r in rs), "/", len(rs), "· wrong money out", sum(r["wrong_money"] for r in rs),
              "· avg tokens", round(sum(r["tokens"] for r in rs) / max(1, len(rs))), "· avg calls", round(sum(r["calls"] for r in rs) / max(1, len(rs)), 1),
              "· errors", sum(1 for r in res if r["cond"] == c and "error" in r))
