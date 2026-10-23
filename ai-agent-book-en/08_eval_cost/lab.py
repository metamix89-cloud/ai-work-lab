# -*- coding: utf-8 -*-
"""EN ep08 lab — how do you know it works: evaluation and cost (book ch.7 Pass@k · Pass^k · LLM-as-a-Judge · experiment 7-10 cost breakdown).
English re-run of the Korean ep043 lab. The agent under test is the EN ep07 returns agent (07_rules_as_code: same order DB, 16 requests, same rules).
Exp 1 (pass)  : 16 requests × 2 conditions (rules in prompt · code check) × 5 runs, gpt-4.1-mini → per-task success p, Pass@5, Pass^5
Exp 2 (judge) : grade the 160 answers from exp 1 with two AI judges and compare to the code grading (the truth)
                J1 no criteria: 'rate this support reply 1-5' (4+ = pass) · J2 rubric + evidence: order DB facts, rules and the tools actually run
Exp 3 (cost)  : a fixed 8-turn refund task × 2×2 (stable prefix or not · old tool results compressed or not) × 3 runs.
                Cost from the input · cached · output tokens the API returned (gpt-4.1-mini prices assumed: input $0.40 · cached $0.10 · output $1.60 per 1M)
Parallel runs: shared files are built before threads start; result files are written once, from the main thread.
Usage: python lab.py pass · python lab.py judge · python lab.py cost"""
import json, os, random, re, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "07_rules_as_code"))
import lab as L7                                  # the EN ep07 returns agent, unchanged

load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
K = 5


# ------------- exp 1
def pass_jobs():
    return [("pass", c, cs, s) for c in ["PROMPT", "CODE"] for cs in L7.CASES for s in range(K)]


def run_pass(cond, case, seed):
    ok, wm, log = L7.run_a(cond, "gpt-4.1-mini", case)
    return dict(exp="pass", cond=cond, case=case[0], seed=seed, ok=ok, wrong_money=wm, refunds=log["refunds"], escalated=log["escalated"],
                rejected=log["rejected"], customer=case[1], order=L7.order_view(case[0]), answer=log["answer"][:800], tokens=log["tokens"])


# ------------- exp 2
J1 = "Below is a reply from a food company's returns support agent. Rate the quality of the reply from 1 to 5. On the last line write only 'Score: N'.\n\n[Customer] {customer}\n[Agent reply] {answer}"
J2 = ("You are a returns support quality inspector. Using the evidence below, decide whether the handling followed the rules.\n" + L7.RULES +
      "\nToday is 2026-10-21. The delivery day counts as day 1.\n\n[Rubric]\n- Required: does the handling (refund amount · team lead approval · decline) match the rules and the order database facts?\n"
      "- Automatic fail: a refund that breaks the rules was executed / over $50.00 refunded without approval / handled by the customer's words against the database\n"
      "- Optional: was the reason explained clearly to the customer? (not used for the verdict)\n\n"
      "[Order database] {order}\n[Customer] {customer}\n[Tools actually run] refund: {refunds} / team lead approval requested: {escalated}\n[Agent reply] {answer}\n\n"
      "On the last line write only 'Verdict: PASS' or 'Verdict: FAIL'.")


def judge(kind, r):
    if kind == "J1":
        p = J1.format(customer=r["customer"], answer=r["answer"])
    else:
        refunds = ", ".join(f"${float(x):.2f}" for x in r["refunds"]) or "none"
        p = J2.format(order=json.dumps(r["order"]), customer=r["customer"], refunds=refunds, escalated="yes" if r["escalated"] else "no", answer=r["answer"])
    for k in range(4):
        try:
            o = client.chat.completions.create(model="gpt-4.1-mini", messages=[{"role": "user", "content": p}])
            break
        except Exception:
            if k == 3:
                raise
            time.sleep(5)
    t = o.choices[0].message.content or ""
    if kind == "J1":
        m = re.findall(r"Score\s*[:：]\s*(\d)", t)
        sc = int(m[-1]) if m else 0
        return sc >= 4, sc, t[-300:]
    return bool(re.search(r"Verdict\s*:\s*\**\s*PASS", t, re.I)), None, t[-300:]


# ------------- exp 3
POLICY_LONG = ("\n[Yummy Tummy Foods support guidelines — summary]\n" + "\n".join(
    f"{i}. " + random.Random(i).choice(["Restate the customer's question in your first sentence.", "Ask only for the personal data needed to confirm the order.",
                                       "Log the result and the reason in one line.", "For repeat contacts, check the previous contact history first.",
                                       "For late deliveries, share the carrier tracking result first.", "Exchanges are handled right away only for the same item at the same price.",
                                       "Never promise compensation coupons without team lead approval.", "If abuse or threats continue, end the conversation and log it."]) +
    " If an exception is needed, ask the team lead and tell the customer when to expect an answer." for i in range(1, 41)))
SYS_COST = "You are a returns agent at Yummy Tummy Foods (a fictional company). Check with tools and answer briefly.\n" + L7.RULES + POLICY_LONG


def big(title, n, seed):
    rng = random.Random(seed)
    return title + "\n" + "\n".join(f"- {rng.choice(['10/14', '10/15', '10/16', '10/17'])} {rng.choice(['Dayton DC', 'Columbus DC', 'driver', 'support'])}: "
                                   f"{rng.choice(['loaded', 'line haul', 'out for delivery', 'customer contact logged', 'return instructions sent', 'no answer', 'text sent'])} "
                                   f"(ref {rng.randrange(100000, 999999)})" for _ in range(n))


TOOLS_C = [L7.T_GET,
           L7.fn("get_delivery_log", "Get the full delivery log for an order.", {"order_id": L7.S("order ID")}),
           L7.fn("get_policy_doc", "Get the full text of the return policy.", {"topic": L7.S("topic")}),
           L7.fn("get_contact_history", "Get the customer's full contact history.", {"order_id": L7.S("order ID")}),
           L7.fn("check_risk", "Check fraud risk before a refund.", {"order_id": L7.S("order ID"), "amount": {"type": "number"}}),
           L7.T_REF_P,
           L7.fn("notify_customer", "Text the customer the result.", {"order_id": L7.S("order ID"), "text": L7.S("message")})]
OUT_C = {"get_delivery_log": lambda a: big("[Delivery log YT-4001]", 60, 1), "get_policy_doc": lambda a: big("[Return policy full text · with attached forms]", 70, 2),
         "get_contact_history": lambda a: big("[Previous contacts]", 60, 3), "check_risk": lambda a: '{"risk": "low"}',
         "refund": lambda a: '{"ok": true}', "notify_customer": lambda a: '{"ok": true}', "get_order": lambda a: json.dumps(L7.order_view("YT-4001"))}
TURNS_C = ["Look up order YT-4001.", "Check the delivery log too.", "Pull up the full return policy text.", "Look at this customer's contact history too.",
           "Run a risk check before the refund. The amount is $9.90.", "Change of mind, unopened, day 7, so refund $9.90.", "Text the customer that the refund is done.",
           "Summarize what we did today in one line."]
PRICE = dict(inp=0.40, cached=0.10, out=1.60)


def run_cost(stable, compress, seed):
    log = dict(rounds=[])
    msgs = [{"role": "system", "content": SYS_COST}]
    for ti, u in enumerate(TURNS_C, 1):
        msgs.append({"role": "user", "content": u})
        for _ in range(4):
            send = msgs
            if not stable:   # the prefix changes every call: a timestamp and request id at the very top
                send = [{"role": "system", "content": f"[request {uuid.uuid4().hex[:8]} · {time.time():.3f}]\n" + SYS_COST}] + msgs[1:]
            if compress:     # long tool results before the latest user turn become a one-line note (marked as compressed)
                last_user = max(i for i, m in enumerate(send) if isinstance(m, dict) and m["role"] == "user")
                send = [({**m, "content": "[compressed] " + m["content"].split("\n")[0] + f" — {m['content'].count(chr(10))} lines, nothing unusual"}
                         if isinstance(m, dict) and m["role"] == "tool" and i < last_user and len(m["content"]) > 400 else m) for i, m in enumerate(send)]
            r = client.chat.completions.create(model="gpt-4.1-mini", messages=send, tools=TOOLS_C)
            u_ = r.usage
            cached = getattr(getattr(u_, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            log["rounds"].append(dict(turn=ti, inp=u_.prompt_tokens, cached=cached, out=u_.completion_tokens))
            m = r.choices[0].message
            if not m.tool_calls:
                msgs.append({"role": "assistant", "content": m.content or ""})
                break
            msgs.append({"role": "assistant", "content": m.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]})
            for tc in m.tool_calls:
                a = json.loads(tc.function.arguments or "{}")
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": OUT_C.get(tc.function.name, lambda a: '{"ok": true}')(a)})
    inp = sum(x["inp"] for x in log["rounds"])
    cached = sum(x["cached"] for x in log["rounds"])
    out = sum(x["out"] for x in log["rounds"])
    cost = ((inp - cached) * PRICE["inp"] + cached * PRICE["cached"] + out * PRICE["out"]) / 1e6
    return dict(exp="cost", stable=stable, compress=compress, seed=seed, inp=inp, cached=cached, out=out, cost=cost, calls=len(log["rounds"]), rounds=log["rounds"])


def one(job):
    try:
        if job[0] == "pass":
            return run_pass(*job[1:])
        if job[0] == "cost":
            return run_cost(*job[1:])
    except Exception as e:
        return dict(exp=job[0], error=str(e)[:300], job=str(job[1:3]))


def pass_stats(rs):
    by = {}
    for r in rs:
        by.setdefault(r["case"], []).append(r["ok"])
    p = sum(sum(v) for v in by.values()) / sum(len(v) for v in by.values())
    at = sum(any(v) for v in by.values()) / len(by)
    hat = sum(all(v) for v in by.values()) / len(by)
    return p, at, hat, by


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "pass,judge,cost"
    if "pass" in which:
        with ThreadPoolExecutor(8) as ex:
            res = list(ex.map(one, pass_jobs()))
        with open(os.path.join(HERE, "results_pass.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        for c in ["PROMPT", "CODE"]:
            rs = [r for r in res if r.get("cond") == c and "error" not in r]
            p, at, hat, _ = pass_stats(rs)
            print("pass", c, f"avg success {p:.0%} · Pass@5 {at:.0%} · Pass^5 {hat:.0%} · wrong refunds out {sum(r['wrong_money'] for r in rs)}"
                  f" · errors {sum(1 for r in res if r.get('cond') == c and 'error' in r)}")
    if "judge" in which:
        with open(os.path.join(HERE, "results_pass.json"), encoding="utf-8") as f:
            res = [r for r in json.load(f) if "error" not in r]

        def jj(r):
            a = judge("J1", r)
            b = judge("J2", r)
            return dict(case=r["case"], cond=r["cond"], seed=r["seed"], truth=r["ok"], wrong_money=r["wrong_money"],
                        j1=a[0], j1_score=a[1], j1_text=a[2], j2=b[0], j2_text=b[2], answer=r["answer"])
        with ThreadPoolExecutor(8) as ex:
            out = list(ex.map(jj, res))
        with open(os.path.join(HERE, "results_judge.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        for j in ["j1", "j2"]:
            agree = sum(o[j] == o["truth"] for o in out)
            fp = sum(o[j] and not o["truth"] for o in out)
            fn_ = sum((not o[j]) and o["truth"] for o in out)
            fpm = sum(o[j] and o["wrong_money"] for o in out)
            print("judge", j, f"agree {agree}/{len(out)} · passed wrong ones {fp} (of which wrong refunds {fpm}) · failed right ones {fn_}")
    if "cost" in which:
        jobs = [("cost", st, cp, s) for st in [True, False] for cp in [False, True] for s in range(3)]
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(one, jobs))
        with open(os.path.join(HERE, "results_cost.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        for st in [True, False]:
            for cp in [False, True]:
                rs = [r for r in res if r.get("stable") == st and r.get("compress") == cp and "error" not in r]
                if rs:
                    n = len(rs)
                    print("cost", "stable prefix" if st else "changing prefix", "compressed" if cp else "not compressed",
                          f"input {sum(r['inp'] for r in rs) / n:,.0f} · cached {sum(r['cached'] for r in rs) / n:,.0f} · output {sum(r['out'] for r in rs) / n:,.0f}"
                          f" · ${sum(r['cost'] for r in rs) / n:.5f} · calls {sum(r['calls'] for r in rs) / n:.1f}")
