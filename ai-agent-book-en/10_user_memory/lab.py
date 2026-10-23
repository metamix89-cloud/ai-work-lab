# -*- coding: utf-8 -*-
"""EN ep10 lab — bonus 1: an agent that remembers you, user memory (book ch.3 'user memory · three-level evaluation · memory formats' · experiments 3-1 · 3-2).
English re-run of the Korean ep045 lab. 12 contact records between a Yummy Tummy Foods (fictional) sales support agent and the account ValueMart
(fictional), June–October 2026. 12 questions (3 levels × 4) × 4 conditions × 3 runs, gpt-4.1-mini.
  M0 no memory        : today's question only
  M1 full history     : all 12 contact records pasted in
  M2 search history   : 1 contact = 1 chunk; attach the 3 most similar contacts (embedding search)
  M3 memory card      : after each contact the model rewrites a JSON memory card (overwrite changed facts, keep a history line) → attach only the card.
                        The card is rebuilt for every run.
Graded by answer checks written in advance; level 3 checks that it flagged what to take care of first. The grader is self-tested by test_grade.py.
Parallel runs: the embedding cache is built before threads start.
Usage: python lab.py [M0,M1,M2,M3] [runs]"""
import json, math, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
MODEL = "gpt-4.1-mini"
EMB = "text-embedding-3-small"
TRIALS = 3

S = [  # (date, contact record) — ValueMart purchasing
 ("2026-06-03", """Customer (Jenna Lee, buyer): Hi, this is Jenna Lee from ValueMart purchasing. We're just starting to work with you.
Agent: Welcome! Your account code is set up as VM-2207.
Customer: Please send invoices to ap@valuemart.example.
Agent: Done. Anything else you need?
Customer: Just the catalog for today. Hot out there, isn't it?
Agent: It is! I'll send the summer promo items first."""),
 ("2026-06-17", """Customer (Jenna Lee): We have two warehouses. The Columbus main DC only has dry storage; frozen and refrigerated go only to Dayton DC 2.
Agent: So frozen and refrigerated to Dayton DC 2, pantry items to Columbus.
Customer: Right. Mixed loads get sent back. By the way, Dayton has forklifts, so pallets are fine there.
Agent: Got it."""),
 ("2026-07-01", """Customer (Jenna Lee): Our store policy changed. Any product containing nuts must have an allergen sticker on the package, or we can't receive it.
Agent: Nut or peanut products need an allergen sticker. Noted.
Customer: Also, the pepperoni pizza did great in our July promo. Let's do another promo together."""),
 ("2026-07-15", """Customer (Jenna Lee): Dayton DC 2 only accepts frozen trucks on Tuesdays and Thursdays.
Agent: We'll schedule frozen deliveries for Tuesdays and Thursdays.
Customer: For payment, we close at month-end and pay cash on the 15th of the following month.
Agent: Payment terms are on file."""),
 ("2026-07-29", """Customer (Jenna Lee): What's your price on BBQ Sauce 18 oz?
Agent: $102.00 per case. 3% off for 100 cases or more.
Customer: Just 40 cases this time. It's pantry, so Columbus.
Agent: Booked for the Columbus main DC."""),
 ("2026-08-05", """Customer (Jenna Lee): About vendor paperwork: the copy of your food safety certificate (HACCP certificate) we have on file is valid until October 31, 2026.
Agent: Then we need to send you a new copy before it expires.
Customer: Yes. Once it expires we can't receive anything from you. Please send it early."""),
 ("2026-08-19", """Customer (Jenna Lee): Starting in August, Dayton DC 2 takes frozen deliveries on Monday, Wednesday and Friday instead.
Agent: We'll switch frozen deliveries to Monday, Wednesday and Friday.
Customer: Thanks. And please send a quote for holiday gift baskets."""),
 ("2026-09-02", """Customer (Jenna Lee): For the fall holiday, we'll take 200 of Holiday Gift Basket B. Pantry, so Columbus.
Agent: Booked. We'll deliver by September 20.
Customer: Great. Oh, add 30 Nut Assortment gift sets too.
Agent: The nut sets will go to Columbus with them."""),
 ("2026-09-16", """Customer (Jenna Lee): Sorry, Dayton DC 2 went back to Tuesday and Thursday for frozen. We don't have the staff for Monday, Wednesday, Friday.
Agent: We'll switch frozen deliveries back to Tuesdays and Thursdays.
Customer: Yes, it's Tuesday and Thursday from now on."""),
 ("2026-09-30", """Customer (Jenna Lee): I'm moving to another department next month. From October, Sam Park will be ValueMart's buyer.
Agent: Thank you for everything. How can we reach Sam Park?
Customer: Extension 4417. Email is sam.park@valuemart.example."""),
 ("2026-10-07", """Customer (Sam Park, buyer): Hi, I'm Sam Park, I've taken over. Payment terms change starting with October: month-end close, cash on the 10th of the following month.
Agent: So from the 15th to the 10th? We'll apply it from October.
Customer: Yes. Everything else Jenna set up stays the same."""),
 ("2026-10-14", """Customer (Sam Park): We're planning a November promo and thinking about adding the Mac & Cheese Bake. That's frozen, right?
Agent: Yes, it's frozen. Should we send a sample next week?
Customer: Yes, just one case of samples to our office (the Columbus main DC). We'll decide the main order later."""),
]

Q = [  # (id, level, question, answer check)
 ("L1-1", 1, "What was ValueMart's account code?", lambda t: "VM-2207" in t),
 ("L1-2", 1, "Which email do ValueMart's invoices go to?", lambda t: "ap@valuemart.example" in t),
 ("L1-3", 1, "What price did we quote ValueMart for BBQ Sauce 18 oz?", lambda t: bool(re.search(r"\$\s?102(\.00)?\b", t))),
 ("L1-4", 1, "How many holiday gift baskets did ValueMart order for the fall holiday? (not the nut sets)", lambda t: bool(re.search(r"\b200\b", t))),
 ("L2-1", 2, "I'm sending ValueMart 50 cases of Pepperoni Pizza. Which warehouse should it go to?",
  lambda t: "Dayton" in t and not re.search(r"(send|ship|deliver)[^.]{0,40}to (the )?Columbus", t, re.I)),
 ("L2-2", 2, "What days does ValueMart's Dayton DC 2 take frozen deliveries now?",
  lambda t: bool(re.search(r"Tue(s|sday)?s?\.?\s*(and|&|/|,)\s*Thu", t, re.I)) and not re.search(r"(now|currently)[^.]{0,30}Mon(day)?s?,?\s*Wed", t, re.I)),
 ("L2-3", 2, "Who is ValueMart's buyer now, and how do I reach them?", lambda t: "Sam Park" in t and "4417" in t),
 # 10th required; a 15th is fine only when it is mentioned as the old value ('from the 15th', 'changed', 'previously' …)
 ("L2-4", 2, "When will ValueMart pay for November?", lambda t: bool(re.search(r"\b10th\b|\b10 (of|in) December|December 10", t, re.I))
  and (not re.search(r"\b15th\b", t) or bool(re.search(r"from the 15th|15th to|changed|previous|used to|was the 15th|instead of", t, re.I)))),
 ("L3-1", 3, "Sam Park at ValueMart says: 'Please deliver 100 cases of pepperoni pizza to Dayton next Monday (10/26).' Write a confirmation text.",
  lambda t: bool(re.search(r"Tue|Thu", t)) and bool(re.search(r"Monday[^.]{0,60}(not|can't|cannot|isn't|unable|only)|only[^.]{0,40}(Tue|Thu)", t, re.I))),
 ("L3-2", 3, "Get 50 more Nut Assortment gift sets ready for ValueMart. Flag anything I should check.",
  lambda t: bool(re.search(r"allergen", t, re.I)) and "Columbus" in t),
 ("L3-3", 3, "We're scheduling ValueMart's November promo deliveries. Anything to take care of before the first delivery on November 5?",
  # '2026-10-31' was missing at first and one right answer was marked wrong — fixed and re-graded (regrade.py, NOTES.md)
  lambda t: bool(re.search(r"certificate", t, re.I)) and bool(re.search(r"October 31|Oct\.? 31|10/31|10-31", t))),
 ("L3-4", 3, "ValueMart just ordered 200 cases of Mac & Cheese Bake. Plan the delivery.",
  lambda t: "Dayton" in t and bool(re.search(r"Tue|Thu", t))),
]

SYS = ("You are a sales support agent at Yummy Tummy Foods (a fictional company). Today is Wednesday, 2026-10-21. Answer briefly in English. "
       "Use only what is in [Memory] about the account; if it's not there, say you don't know. When handling a task, flag anything in the account's conditions that could be a problem, first.")
CARD_SYS = ("You maintain an account memory card. After each contact, rewrite the account's memory card (JSON). Keep only facts useful for future work "
            "(drop greetings and small talk). Overwrite changed facts with the latest value, and add one line to 'history' saying when what changed to what. "
            "Copy dates, amounts, codes and contact details exactly. Output JSON only.")


def chat(msgs, log):
    for k in range(4):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs)
            break
        except Exception:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    log["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
    return r.choices[0].message.content or ""


def full_text(sessions):
    return "\n\n".join(f"[Contact {d}]\n{t}" for d, t in sessions)


EMB_CACHE = os.path.join(HERE, "emb_sessions.json")


def session_vecs():
    if os.path.exists(EMB_CACHE):
        with open(EMB_CACHE) as f:
            return json.load(f)
    v = [d.embedding for d in client.embeddings.create(model=EMB, input=[f"[Contact {d}]\n{t}" for d, t in S]).data]
    with open(EMB_CACHE, "w") as f:
        json.dump(v, f)
    return v


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def build_card(log):
    card = "{}"
    for d, t in S:
        card = chat([{"role": "system", "content": CARD_SYS},
                     {"role": "user", "content": f"[Current memory card]\n{card}\n\n[New contact {d}]\n{t}\n\nRewritten memory card (JSON):"}], log)
        card = re.sub(r"^```(json)?|```$", "", card.strip(), flags=re.M).strip()
    return card


def memory_for(cond, q, card, vecs, log):
    if cond == "M0":
        return "(no memory)"
    if cond == "M1":
        return full_text(S)
    if cond == "M2":
        qv = client.embeddings.create(model=EMB, input=[q]).data[0].embedding
        top = sorted(range(len(S)), key=lambda i: -cos(qv, vecs[i]))[:3]
        log["retrieved"] = [S[i][0] for i in sorted(top)]
        return full_text([S[i] for i in sorted(top)])
    return "[Account memory card — ValueMart]\n" + card


def run_trial(cond, seed, vecs):
    card, card_tokens = "", 0
    if cond == "M3":
        cl = dict(tokens=0)
        card = build_card(cl)
        card_tokens = cl["tokens"]
    out = []
    for qid, lv, q, chk in Q:
        ql = dict(tokens=0)
        mem = memory_for(cond, q, card, vecs, ql)
        ans = chat([{"role": "system", "content": SYS + "\n\n[Memory]\n" + mem}, {"role": "user", "content": q}], ql)
        out.append(dict(cond=cond, seed=seed, q=qid, level=lv, ok=chk(ans), answer=ans[:700], tokens=ql["tokens"], retrieved=ql.get("retrieved")))
    return dict(cond=cond, seed=seed, card=card, card_tokens=card_tokens, answers=out)


if __name__ == "__main__":
    conds = sys.argv[1].split(",") if len(sys.argv) > 1 else ["M0", "M1", "M2", "M3"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    vecs = session_vecs()              # once, before threads start
    jobs = [(c, s) for c in conds for s in range(trials)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: run_trial(j[0], j[1], vecs), jobs))
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for c in conds:
        A = [a for r in res if r["cond"] == c for a in r["answers"]]
        print(c, "correct", sum(a["ok"] for a in A), "/", len(A), "|",
              " ".join(f"L{l} {sum(a['ok'] for a in A if a['level'] == l)}/{sum(1 for a in A if a['level'] == l)}" for l in (1, 2, 3)),
              "| tokens per question", round(sum(a["tokens"] for a in A) / len(A)),
              "| card building tokens", round(sum(r["card_tokens"] for r in res if r["cond"] == c) / trials))
