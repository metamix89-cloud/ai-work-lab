# -*- coding: utf-8 -*-
"""EN ep04 lab — when the conversation gets long: comparing context-compression strategies (book ch.2 experiment 2-10 style).
English re-run of the Korean ep039 lab. A 20-turn day with a ValueMart (fictional) buyer. Long tool results pile up
(catalogs, stock sheet, notices), and 6 facts settled during the day must appear correctly in the final order confirmation.
The window limit is deliberately small (BUDGET tokens), like the book: the model's own window is bigger, but crossing BUDGET counts as a failure.
  S0 reference: no limit   : keep everything, no limit check (the baseline when the window is big enough)
  S1 no compression        : keep everything
  S2 truncate              : keep only the last 8 user turns
  S3 generic summary       : every tool result is replaced by a task-blind '3-5 sentence summary'
  S4 task-aware summary    : summarize with the current question + recent chat, keep facts needed later
  S5 batch near the limit  : only when input passes 80% of BUDGET, compress all uncompressed tool results the S4 way
  S6 progress notes        : like S2 (last 8 turns), but the agent writes settled facts with save_note, and the note is always shown
Usage:
  python lab.py S0 1 probe.json             → measure the uncompressed peak to set BUDGET (Korean run: BUDGET = 87% of the S0 peak)
  python lab.py S0,S1,S2,S3,S4,S5,S6 5      → results.json
  --budget=N overrides BUDGET."""
import json, os, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
MODEL = "gpt-4.1-mini"
BUDGET = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--budget=")), 24000)
WINDOW = 8
TRIALS = 5

# -- long tool results (fictional data, fixed seeds)
NAMES = {
    "frozen": ["Pepperoni Pizza 2-pack", "Mac & Cheese Bake", "Chicken Nuggets 2 lb", "Premium Steak Gift Box", "Beef Burritos 8-pack", "Fish Sticks",
               "Waffles 10-count", "Breakfast Sandwiches", "Mozzarella Sticks", "French Fries 5 lb", "Tater Tots", "Meatballs 2 lb", "Corn Dogs 6-pack",
               "Cheese Pizza 2-pack", "Ice Cream Sandwiches", "Chicken Pot Pie", "Lasagna Family Size", "Burger Patties 12-pack", "Pancakes 12-count", "Mixed Berries 3 lb"],
    "pantry": ["BBQ Sauce 18 oz", "Cola 12-pack", "Ketchup 32 oz", "Peanut Butter 40 oz", "Potato Chips Party Size", "Tortilla Chips", "Pasta Sauce 24 oz",
               "Spaghetti 2 lb", "Mac & Cheese Boxes 6-pack", "Pancake Mix", "Maple Syrup", "Canned Beans 6-pack", "Tuna Cans 4-pack", "Honey 16 oz",
               "Granola Bars 12-count", "Popcorn 6-pack", "Root Beer 12-pack", "Lemonade 12-pack", "Sesame Burger Buns 8-pack", "Cereal Family Size"],
    "refrigerated": ["Handmade Burger Patties", "Fresh Salsa", "Hummus 2-pack", "Cheddar Slices", "Bacon 1 lb", "Hot Dogs 8-pack", "Milk 1 gal",
                     "Greek Yogurt 4-pack", "Salad Kit", "Orange Juice 52 oz", "Butter 1 lb", "Eggs 18-count", "Deli Turkey", "Coleslaw", "Potato Salad",
                     "Guacamole", "String Cheese", "Cream Cheese", "Sour Cream", "Pizza Dough"],
    "gift": ["Holiday Gift Basket A", "Holiday Gift Basket B", "Snack Gift Box", "Premium Steak Gift Box VIP", "BBQ Sauce Gift Set", "Cookie Tin", "Popcorn Tin",
             "Hot Cocoa Set", "Nut Assortment", "Coffee Sampler", "Olive Oil Set", "Cheese & Crackers Box", "Jerky Sampler", "Candy Box", "Tea Set",
             "Fruit Basket", "Chocolate Truffles", "Holiday Ham Box", "Maple Syrup Set", "Spice Set"],
}


def catalog(cat):
    rng = random.Random(1)
    rows = []
    for i, n in enumerate(NAMES[cat] * 3):
        code = "YT-%s%d" % ({"frozen": "F", "pantry": "P", "refrigerated": "R", "gift": "G"}[cat], 100 + i)
        price = rng.randrange(30, 900) / 10
        size = "" if i < len(NAMES[cat]) else " (" + ["bulk", "food service"][i // len(NAMES[cat]) - 1] + ")"
        rows.append(f"{code} | {n}{size} | {rng.choice([6, 8, 10, 12, 20, 24])} units/case | list ${price:,.2f} | promo ${price * rng.choice([0.85, 0.9, 0.95]):,.2f} | "
                    f"shelf life {rng.choice(['6 months', '9 months', '12 months', '18 months', '10 days', '14 days', '30 days'])} | storage {cat} | "
                    f"origin {rng.choice(['USA', 'USA/imported', 'imported (Canada)', 'imported (Mexico)'])} | min order {rng.choice([5, 10, 20])} cases | "
                    f"note {rng.choice(['-', 'new packaging soon', 'new', 'promo pick', 'limited stock'])}")
    if cat == "frozen":
        rows[0] = ("YT-F100 | Pepperoni Pizza 2-pack | 10 units/case | list $52.00 | promo $46.80 | shelf life 12 months | storage frozen | origin USA | "
                   "min order 10 cases | note promo pick")
    return f"[Yummy Tummy Foods {cat} catalog, 2026 H2]\ncode | product | pack | list | promo | shelf life | storage | origin | min order | note\n" + "\n".join(rows)


def stock_report():
    rng = random.Random(2)
    rows = []
    for cat in ["frozen", "pantry", "refrigerated"]:
        for j, n in enumerate(NAMES[cat] * 2):
            n = n if j < len(NAMES[cat]) else n + " (food service)"
            rows.append(f"{n} | {cat} | on hand {rng.randrange(20, 2000)} cases | shipped this week {rng.randrange(10, 400)} cases | "
                        f"restock {rng.choice(['10/27', '10/29', '11/3', '11/5', 'none'])} | status {rng.choice(['OK', 'OK', 'OK', 'running low'])}")
    rows[1] = ("Mac & Cheese Bake | frozen | on hand 0 cases | shipped this week 0 cases | restock 11/5 → delayed to 11/12 (cheese sauce supply issue) | "
               "status can ship from 11/12")
    return "[Warehouse stock sheet · as of 10/21 9:00 AM]\nitem | category | on hand | shipped this week | restock | status\n" + "\n".join(rows)


def delivery_schedule():
    rng = random.Random(3)
    regions = ["Columbus", "Dayton", "Cincinnati", "Cleveland", "Toledo", "Akron", "Indianapolis", "Fort Wayne", "Louisville", "Lexington", "Detroit",
               "Grand Rapids", "Pittsburgh", "Erie", "Chicago North", "Chicago South", "Milwaukee", "Madison", "St. Louis", "Kansas City", "Nashville",
               "Memphis", "Atlanta", "Charlotte"]
    rows = [f"{r} | {d} | pantry trucks {rng.choice(['daily', 'Mon/Wed/Fri', 'Tue/Thu'])} | frozen trucks {rng.choice(['Mon/Wed/Fri', 'Tue/Thu', 'daily'])} | "
            f"order cutoff {rng.choice(['3 PM the day before', '5 PM the day before', '3 PM two days before'])} | note {rng.choice(['-', 'closed on holidays', 'extra trucks in Nov'])}"
            for r in regions for d in ["supermarket", "convenience", "online fulfillment"]]
    return "[Yummy Tummy Foods delivery schedule · November]\nregion | customer type | pantry trucks | frozen trucks | order cutoff | note\n" + "\n".join(rows)


def notice(kind):
    rng = random.Random(4)
    paras = [f"{i}. Due to changes in {rng.choice(['freight', 'packaging', 'raw materials', 'labor', 'exchange rates'])}, the "
             f"{rng.choice(['supply terms', 'minimum order quantity', 'case size', 'order cutoff time'])} for {rng.choice(['some items', 'gift sets', 'food-service items'])} "
             f"may be {rng.choice(['adjusted', 'changed', 'reviewed'])}. Please contact your sales representative for details. "
             f"This applies from {rng.choice(['October', 'November', 'December'])} {rng.randrange(1, 28)} and may vary by account contract." for i in range(1, 46)]
    if kind == "price":
        paras.insert(27, "28. [IMPORTANT] The 3% supply price increase for frozen products (pizza, mac & cheese, nuggets, etc.), originally scheduled for "
                         "November 1, is postponed to December 1. The 2% increase for pantry products takes effect on November 1 as planned.")
        title = "[Notice] 2026 H2 supply prices and trade terms"
    else:
        title = "[Notice] Return and exchange rules for accounts"
    return title + "\n" + "\n".join(paras)


def sales_history():
    rng = random.Random(5)
    rows = [f"2025-{m} | {n} | sold {rng.randrange(50, 3000)} cases | promo {rng.choice(['yes', 'no'])} | return rate {rng.randrange(0, 40) / 10}%"
            for m in [9, 10, 11, 12] for n in NAMES["frozen"] + NAMES["pantry"][:10]]
    return "[ValueMart delivery history, Sep-Dec 2025]\n" + "\n".join(rows)


TOOL_IMPL = {
    "get_catalog": lambda a: catalog(a.get("category", "frozen") if a.get("category") in NAMES else "frozen"),
    "get_stock_report": lambda a: stock_report(),
    "get_delivery_schedule": lambda a: delivery_schedule(),
    "get_notice": lambda a: notice("return" if "return" in a.get("topic", "").lower() else "price"),
    "get_sales_history": lambda a: sales_history(),
}


def fn(name, d, props):
    return {"type": "function", "function": {"name": name, "description": d, "parameters": {
        "type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()}, "required": list(props)}}}


TOOLS = [fn("get_catalog", "Get the full product catalog for a category.", {"category": "one of frozen, pantry, refrigerated, gift"}),
         fn("get_stock_report", "Get the full warehouse stock sheet.", {}),
         fn("get_delivery_schedule", "Get the delivery schedule by region.", {}),
         fn("get_notice", "Get an account notice document.", {"topic": "'price' or 'returns'"}),
         fn("get_sales_history", "Get last year's delivery history for ValueMart.", {})]
T_NOTE = fn("save_note", "Write what was settled or changed in today's conversation to the progress note. Pass the whole note each time (rewrite anything that changed).",
            {"text": "the whole note"})

SYS = ("You are a sales support agent at Yummy Tummy Foods (a fictional company). You help a ValueMart purchasing buyer with an order, all day long. "
       "Use the tools to look things up when needed. Keep answers short. Never make things up.")
SYS_NOTE = ("\nThe conversation is long, so older turns get cut. Whenever something is settled or changed (quantity, ship-to, days, dates, terms), "
            "update the progress note right away with save_note.")

TURNS = [
    "Hi, this is Taylor from ValueMart purchasing. We're planning next month's promo, so I'll be asking you things all day. First, show me the frozen catalog.",
    "What's the promo price on the Pepperoni Pizza 2-pack?",
    "Great. Let's lock in 120 cases of Pepperoni Pizza 2-pack for the promo.",
    "Show me the pantry catalog too.",
    "Oh, and for this order, ship to ValueMart Distribution Center 2 in Dayton, Ohio, not our main store.",
    "Let me see the refrigerated catalog.",
    "Check the stock status for the Mac & Cheese Bake.",
    "How many units per case for the Cola 12-pack?",
    "Show me the November delivery schedule.",
    "Is there a notice about supply prices?",
    "What's the shelf life on the BBQ Sauce 18 oz?",
    "Payment terms: invoice at month-end, paid in cash on the 15th of the following month.",
    "Show me the gift set catalog.",
    "I think the promo will do well, so make the pizza 150 cases instead of 120.",
    "Do you have our delivery history from last September to December?",
    "By the way, our Distribution Center 2 only takes frozen trucks on Tuesdays and Thursdays.",
    "I'm thinking about adding Chicken Nuggets 2 lb to the promo. Show me the stock status again.",
    "Hmm... let's leave the nuggets out this time.",
    "Show me the returns policy notice too.",
    "Write up the order confirmation with everything we agreed today. Include item and quantity, ship-to, frozen delivery days, "
    "when the frozen price increase applies, payment terms, and when the Mac & Cheese Bake can ship.",
]

FACTS = [("150 cases", lambda t: bool(re.search(r"\b150\s*cases?\b", t, re.I))),
         ("ship to DC 2", lambda t: bool(re.search(r"Distribution Center 2|\bDC\s*2\b|Dayton", t, re.I))),
         ("frozen Tue/Thu", lambda t: bool(re.search(r"Tue(s|sday)?s?\.?\s*(and|&|/|,)\s*Thu(r|rs|rsday)?", t, re.I))),
         ("price increase Dec 1", lambda t: bool(re.search(r"Dec(ember)?\.?\s*1(st)?\b|\b12/1\b|2026-12-01", t, re.I))),
         # a '15' on a payment line only — the first version matched any 15, e.g. a made-up "Effective November 15" (see NOTES.md)
         ("pay on the 15th", lambda t: any(re.search(r"\b15(th)?\b", l) and re.search(r"pay|month", l, re.I)
                                           and not re.search(r"(Oct|Nov|Dec)[a-z]*\.?\s*15\b", l) for l in t.splitlines())),
         ("mac & cheese 11/12", lambda t: bool(re.search(r"Nov(ember)?\.?\s*12(th)?\b|\b11/12\b|2026-11-12", t, re.I)))]


def chat(messages, tools=None, log=None, kind="main"):
    kw = dict(model=MODEL, messages=messages)
    if tools:
        kw["tools"] = tools
    for k in range(4):
        try:
            r = client.chat.completions.create(**kw)
            break
        except Exception:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    if log is not None:
        log["tokens_" + kind] += r.usage.prompt_tokens + r.usage.completion_tokens
    return r


def summarize(text, log, task_aware=False, query="", recent=""):
    if task_aware:
        p = (f"You keep the records for a sales support agent. Shorten the tool result below.\nThe buyer's current question: {query}\nRecent chat:\n{recent}\n\n"
             "Rules: keep only facts needed for this question and for the order later. Copy numbers, dates, changes and exceptions exactly; "
             "drop unrelated rows. At most 10 lines.\n\nTool result:\n" + text)
    else:
        p = "Summarize the following document in 3-5 sentences.\n\n" + text
    r = chat([{"role": "user", "content": p}], log=log, kind="compress")
    return r.choices[0].message.content or ""


def recent_text(messages, n=6):
    out = []
    for m in messages[-n:]:
        role = m["role"] if isinstance(m, dict) else m.role
        c = m.get("content") if isinstance(m, dict) else m.content
        if role in ("user", "assistant") and c:
            out.append(f"{role}: {c[:300]}")
    return "\n".join(out)


def window(messages, turns):
    """Keep only the last `turns` user turns (and the system message)."""
    idx = [i for i, m in enumerate(messages) if isinstance(m, dict) and m["role"] == "user"]
    if len(idx) <= turns:
        return messages
    return [messages[0]] + messages[idx[-turns]:]


def compress_all(history, log, user):
    for h in history:
        if isinstance(h, dict) and h["role"] == "tool" and not h["content"].startswith("[COMPRESSED]") and len(h["content"]) > 500:
            h["content"] = "[COMPRESSED] " + summarize(h["content"], log, True, user, recent_text(history))
            log["compressions"] += 1


def run(strategy, seed):
    log = dict(tokens_main=0, tokens_compress=0, overflow_turn=None, max_prompt=0, notes="", compressions=0, calls=[])
    sys_txt = SYS + (SYS_NOTE if strategy == "S6" else "")
    history = [{"role": "system", "content": sys_txt}]
    tools = TOOLS + ([T_NOTE] if strategy == "S6" else [])
    final = ""
    for ti, user in enumerate(TURNS, 1):
        history.append({"role": "user", "content": user})
        for _ in range(6):
            msgs = history
            if strategy in ("S2", "S6"):
                msgs = window(history, WINDOW)
            if strategy == "S6" and log["notes"]:
                msgs = [{"role": "system", "content": sys_txt + "\n\n[Progress note]\n" + log["notes"]}] + msgs[1:]
            r = chat(msgs, tools, log)
            pt = r.usage.prompt_tokens
            log["max_prompt"] = max(log["max_prompt"], pt)
            if pt > BUDGET and strategy != "S0":
                log["overflow_turn"] = ti
                return log, ""
            m = r.choices[0].message
            if not m.tool_calls:
                history.append({"role": "assistant", "content": m.content or ""})
                if ti == len(TURNS):
                    final = m.content or ""
                break
            history.append({"role": "assistant", "content": m.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]})
            for tc in m.tool_calls:
                log["calls"].append(f"{ti}:{tc.function.name}")
                try:
                    a = json.loads(tc.function.arguments or "{}")
                except Exception:
                    a = {}
                if tc.function.name == "save_note":
                    log["notes"] = a.get("text", "")
                    out = "note saved"
                else:
                    out = TOOL_IMPL.get(tc.function.name, lambda a: "error: no such tool")(a)
                    if strategy == "S3":
                        out = "[COMPRESSED] " + summarize(out, log)
                        log["compressions"] += 1
                    elif strategy == "S4":
                        out = "[COMPRESSED] " + summarize(out, log, True, user, recent_text(history))
                        log["compressions"] += 1
                history.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            if strategy == "S5" and pt > BUDGET * 0.8:
                compress_all(history, log, user)
        if strategy == "S5" and log["max_prompt"] > BUDGET * 0.8:   # also at the end of a user turn
            compress_all(history, log, user)
    return log, final


def one(job):
    s, seed = job
    t0 = time.time()
    try:
        log, final = run(s, seed)
    except Exception as e:
        return dict(strategy=s, seed=seed, error=str(e)[:300])
    kept = [name for name, f in FACTS if f(final)]
    return dict(strategy=s, seed=seed, kept=kept, n_kept=len(kept), overflow_turn=log["overflow_turn"], max_prompt=log["max_prompt"],
                tokens_main=log["tokens_main"], tokens_compress=log["tokens_compress"], compressions=log["compressions"],
                notes=log["notes"][:1500], calls=log["calls"], final=final[:2500], sec=round(time.time() - t0), budget=BUDGET)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strategies = args[0].split(",") if args else ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]
    trials = int(args[1]) if len(args) > 1 else TRIALS
    out = args[2] if len(args) > 2 else "results.json"
    jobs = [(s, k) for s in strategies for k in range(trials)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, jobs))
    with open(os.path.join(HERE, out), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("BUDGET", BUDGET)
    for s in strategies:
        rs = [r for r in res if r["strategy"] == s and "error" not in r]
        print(s, "facts kept", sum(r["n_kept"] for r in rs), "/", 6 * len(rs), "· overflow", sum(1 for r in rs if r["overflow_turn"]),
              [r["overflow_turn"] for r in rs if r["overflow_turn"]],
              "· avg tokens", round(sum(r["tokens_main"] + r["tokens_compress"] for r in rs) / max(1, len(rs))),
              "· peak input", round(sum(r["max_prompt"] for r in rs) / max(1, len(rs))), "· errors", sum(1 for r in res if r["strategy"] == s and "error" in r))
