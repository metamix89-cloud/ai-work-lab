# -*- coding: utf-8 -*-
"""EN ep02 lab — do the system prompt and tool descriptions change performance? (book ch.2 experiment 2-4 style)
English re-run of the Korean ep035 lab: Yummy Tummy Foods (fictional) returns desk.
5 conditions x 10 customer messages x 3 runs, real gpt-4.1-mini calls -> results.json. Graded from the tool-call log
(answer key written by a human before the run).
  A baseline     : step-by-step SOP + specific rules + full tool descriptions + neutral tone
  B tone only    : same content as A, over-the-top tone and emoji
  C shuffled     : same rules, no numbering, sentences shuffled
  D no tool desc : tool and argument names only, every description removed
  E vague rules  : rules blurred into 'handle it appropriately'
Usage: python lab.py [reps]"""
import json, os, random, sys
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
MODEL = "gpt-4.1-mini"

# -- fictional data (days since delivery precomputed: date math is not what this experiment tests)
CUSTOMERS = {"YT-3101": "5521", "YT-3102": "1180", "YT-3103": "7304", "YT-3104": "2209", "YT-3105": "6612",
             "YT-3106": "3047", "YT-3107": "8890", "YT-3108": "4415", "YT-3109": "9031", "YT-3110": "1276"}
ORDERS = {
    "YT-3101": dict(product="Yummy Tummy Pepperoni Pizza 2-pack", category="frozen", paid=12.90, days_since_delivery=5, opened="no"),
    "YT-3102": dict(product="Yummy Tummy Pepperoni Pizza 2-pack", category="frozen", paid=12.90, days_since_delivery=10, opened="no"),
    "YT-3103": dict(product="Yummy Tummy Cola 12-pack", category="pantry", paid=9.80, days_since_delivery=9, opened="yes"),
    "YT-3104": dict(product="Yummy Tummy BBQ Sauce 18 oz", category="pantry", paid=8.50, days_since_delivery=3, opened="yes"),
    "YT-3105": dict(product="Yummy Tummy Holiday Gift Basket", category="pantry", paid=68.00, days_since_delivery=2, opened="no"),
    "YT-3106": dict(product="Yummy Tummy Pepperoni Pizza 2-pack", category="frozen", paid=12.90, days_since_delivery=4, opened="yes"),
    "YT-3107": dict(product="Yummy Tummy Chicken Nuggets 2 lb", category="frozen", paid=15.90, days_since_delivery=3, opened="no"),
    "YT-3108": dict(product="Yummy Tummy Mac & Cheese Bake", category="frozen", paid=15.90, days_since_delivery=2, opened="no"),
    "YT-3109": dict(product="Yummy Tummy Mac & Cheese Bake", category="frozen", paid=6.90, days_since_delivery=7, opened="no"),
    "YT-3110": dict(product="Yummy Tummy Premium Steak Gift Box", category="frozen", paid=89.00, days_since_delivery=1, opened="yes"),
}
# (customer message, answer key) — refund:amount / escalate / deny / ask
CASES = [
    ("I'd like to return order YT-3101. I just changed my mind. Last 4 digits of my phone: 5521.", ("refund", 9.90)),
    ("Please take back the pizzas, YT-3102. Never opened. Phone ends in 1180.", ("deny", None)),
    ("I opened the cola 12-pack (YT-3103) and don't like the taste. Refund please. Phone ends in 7304.", ("deny", None)),
    ("The BBQ sauce from YT-3104 smells sour, I think it went bad. Please refund me. Last 4 digits are 2209.", ("refund", 8.50)),
    ("Returning gift basket YT-3105, the person I sent it to doesn't need it. Phone ends in 6612.", ("escalate", None)),
    ("I found a piece of plastic in the pizza from YT-3106. I want a refund. Phone ends in 3047.", ("refund", 12.90)),
    ("Return YT-3107 please, changed my mind. Phone ends in 1234.", ("deny_verify", None)),
    ("I want to return the mac & cheese from YT-3108. Haven't opened it yet.", ("ask", None)),
    ("Please return my mac & cheese YT-3109, I changed my mind. It's been exactly one week since it arrived today. Phone ends in 9031.", ("refund", 3.90)),
    ("The steaks in YT-3110 look discolored and smell off. Please refund me. Phone ends in 1276.", ("escalate", None)),
]

# -- tools
TOOL_DESC = {
    "verify_customer": ("Check that the order ID matches the last 4 digits of the phone number the customer gave. Always call this first, before any refund or approval request.",
                        {"order_id": "Order ID, e.g. YT-3101", "phone_last4": "Last 4 digits of the phone number the customer gave"}),
    "get_order": ("Look up the order: product, category (frozen/pantry), amount paid (USD), days since delivery, and whether it was opened.",
                  {"order_id": "Order ID, e.g. YT-3101"}),
    "refund": ("Issue a refund to the customer. Cannot be undone. The amount is the final refund calculated by the rules (USD).",
               {"order_id": "Order ID", "amount": "Refund amount in USD, e.g. 9.90", "reason": "'change of mind' or 'quality issue'"}),
    "escalate": ("Do not handle it yourself; ask a human agent for approval.",
                 {"order_id": "Order ID", "reason": "One line on why approval is needed"}),
}


def tools(with_desc=True):
    out = []
    for name, (desc, params) in TOOL_DESC.items():
        props = {k: ({"type": "number"} if k == "amount" else {"type": "string"}) for k in params}
        if with_desc:
            for k in props:
                props[k]["description"] = params[k]
        f = {"name": name, "parameters": {"type": "object", "properties": props, "required": list(params)}}
        if with_desc:
            f["description"] = desc
        out.append({"type": "function", "function": f})
    return out


# -- system prompts per condition
RULES = [
    "Identity check: before any refund or approval request, call verify_customer with the order ID and the last 4 digits of the phone number. If the customer did not give the last 4 digits, do not proceed; ask for them first. If they do not match, do not proceed.",
    "Return window: frozen items can be returned within 7 days of delivery (day 7 included); pantry items within 14 days.",
    "Opened items: an opened item cannot be returned for a change of mind. Quality issues (foreign object, spoiled, strange smell, etc.) can be returned even if opened.",
    "Refund amount: for a change of mind, subtract the $3.00 return shipping fee from the amount paid. For a quality issue, refund the full amount paid.",
    "High-value approval: if the amount paid is over $50.00, do not refund regardless of the reason; call escalate to request a human agent's approval.",
]
SOP = """# Role
Returns and refunds agent at Yummy Tummy Foods customer support. You handle one customer message today.

# Procedure
Step 1 Identity check — {0}
Step 2 Order lookup — use get_order to check category, amount, days since delivery and whether it was opened.
Step 3 High-value check — {4}
Step 4 Can it be returned? — {1} {2}
Step 5 Amount and action — {3} Call refund with the amount you calculated.
Step 6 Reply — tell the customer the result (or why it cannot be returned) in two sentences or fewer."""
TONE_B = """🎉🎉 Hiiii~~ I'm the BEST returns fairy in the whole universe at Yummy Tummy Foods!! ✨ I'll work SUPER hard to make every customer's day amazing 💖💖
(Here's the really really important stuff 👇👇)
"""


def system_prompt(cond, seed=0):
    body = [r.split(": ", 1)[1] for r in RULES]
    if cond in ("A", "D"):
        return SOP.format(*body)
    if cond == "B":
        return TONE_B + SOP.format(*body).replace("in two sentences or fewer.", "in a super fun and cute way with lots of emoji 🥳")
    if cond == "C":
        bits = body + ["Look up the order with get_order.", "Tell the customer the result in two sentences or fewer."]
        sents = [s.strip() + ("" if s.strip().endswith(".") else ".") for b in bits for s in b.split(". ") if s.strip()]
        random.Random(seed).shuffle(sents)
        return "You are the returns and refunds agent at Yummy Tummy Foods customer support. Follow these. " + " ".join(sents)
    if cond == "E":
        return ("You are the returns and refunds agent at Yummy Tummy Foods customer support. Handle returns and refunds appropriately "
                "for the situation so the customer is satisfied. Check identity if needed, and take the return window and item condition "
                "into account as appropriate. Set a reasonable amount, and be careful with large amounts. "
                "Tell the customer the result in two sentences or fewer.")


# -- tool execution + core loop
def run_tool(name, a):
    oid = a.get("order_id")
    if name == "verify_customer":
        if oid not in CUSTOMERS:
            return {"error": "order not found"}
        return {"match": CUSTOMERS[oid] == str(a.get("phone_last4", "")).strip()}
    if name == "get_order":
        return ORDERS.get(oid, {"error": "order not found"})
    if name == "refund":
        if oid not in ORDERS or not isinstance(a.get("amount"), (int, float)):
            return {"error": "bad order ID or amount format"}
        return {"refunded": a["amount"]}
    if name == "escalate":
        return {"queued": "waiting for human approval"}
    return {"error": "no such tool"}


def agent(cond, msg, seed):
    messages = [{"role": "system", "content": system_prompt(cond, seed)}, {"role": "user", "content": msg}]
    log, final = [], ""
    for _ in range(10):
        m = client.chat.completions.create(model=MODEL, messages=messages, tools=tools(cond != "D")).choices[0].message
        messages.append(m)
        if not m.tool_calls:
            final = m.content or ""
            break
        for tc in m.tool_calls:
            try:
                a = json.loads(tc.function.arguments)
            except Exception:
                a = {}
            r = run_tool(tc.function.name, a)
            log.append({"tool": tc.function.name, "args": a, "result": r})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(r)})
    return log, final


def same_amount(x, y):
    return isinstance(x, (int, float)) and abs(x - y) < 0.005


def grade(gold, log):
    kind, amt = gold
    names = [l["tool"] for l in log]
    refunds = [l for l in log if l["tool"] == "refund"]
    escal = "escalate" in names
    verified_ok = any(l["tool"] == "verify_customer" and l["result"].get("match") is True for l in log)
    first_act = next((i for i, n in enumerate(names) if n in ("refund", "escalate")), None)
    first_ok_verify = next((i for i, l in enumerate(log) if l["tool"] == "verify_customer" and l["result"].get("match") is True), None)
    v = {"order_violation": first_act is not None and (first_ok_verify is None or first_ok_verify > first_act),
         "tool_errors": sum(1 for l in log if "error" in l["result"])}
    if kind == "refund":
        ok = len(refunds) == 1 and same_amount(refunds[0]["args"].get("amount"), amt) and not escal
        why = "correct" if ok else ("wrong amount %s" % refunds[0]["args"].get("amount") if refunds else ("escalated" if escal else "no refund"))
    elif kind == "escalate":
        ok = escal and not refunds
        why = "correct" if ok else ("refunded high-value directly" if refunds else "did not escalate")
    else:   # deny / deny_verify / ask : must not act
        ok = not refunds and not escal
        why = "correct" if ok else ("refunded against the rules" if refunds else "needless escalation")
    if kind == "ask" and ok and verified_ok:
        ok, why = False, "verified without a number?"
    v.update(ok=ok and not v["order_violation"], why=why if not (ok and v["order_violation"]) else "acted before verifying")
    return v


def one(job):
    cond, ci, rep = job
    msg, gold = CASES[ci]
    log, final = agent(cond, msg, seed=rep)
    return dict(cond=cond, case=ci, rep=rep, msg=msg, gold=gold, log=log, final=final, **grade(gold, log))


if __name__ == "__main__":
    REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    jobs = [(c, i, r) for c in "ABCDE" for i in range(len(CASES)) for r in range(REPS)]
    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(one, jobs))
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for c in "ABCDE":
        rs = [r for r in res if r["cond"] == c]
        print(c, "correct %d/%d" % (sum(r["ok"] for r in rs), len(rs)), "· order violations %d" % sum(r["order_violation"] for r in rs),
              "· tool errors %d" % sum(r["tool_errors"] for r in rs))
