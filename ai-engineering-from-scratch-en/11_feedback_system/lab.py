# -*- coding: utf-8 -*-
"""EN es11 lab — Turn every agent correction into a system improvement (source: AI Engineering from Scratch, Phase 14 lesson 46).
English re-run of the Korean 11_feedback_system: a quote-writing AI at Yummy Tummy Foods (fictional). The team lead corrected 3 things last session (CORR);
we measure how often they recur in new sessions depending on how the corrections were kept. 10 new quotes x 2 runs = 20 per condition, gpt-4.1-mini.
  A no record          : a fresh session, no record of the corrections
  B symptom note       : the lead's words, noted as said ("pizza sauce is $79.30" etc.)
  C cause rules        : the cause found and written as a rule ("use the latest price-list row effective on or before the quote date" etc.)
  D cause rules + checker : C + a code checker - if the quote breaks a rule it says which rule, and the AI gets one rewrite
Trap: quotes dated in October (T3 · T5 · T8) should use the OLD price - following the symptom note ('$79.30') gets them wrong. There is also a 2027 price row.
Grading (code): unit prices right · '(tax included)' wording · validity date (quote date + 14 days)."""
import json, os, re, sys, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 2))

PRICES = """[Price list - price per case, tax included]
item,price_usd,effective_date
Pizza Sauce 1 gal,73.40,2026-07-01
Pizza Sauce 1 gal,79.30,2026-11-01
Pizza Sauce 1 gal,82.00,2027-01-01
BBQ Sauce 18 oz,46.20,2026-07-01
BBQ Sauce 18 oz,47.50,2026-11-01
Ranch Dressing 16 oz,39.80,2026-07-01"""
HIST = {"Pizza Sauce 1 gal": [("2026-07-01", 73.40), ("2026-11-01", 79.30), ("2027-01-01", 82.00)],
        "BBQ Sauce 18 oz": [("2026-07-01", 46.20), ("2026-11-01", 47.50)], "Ranch Dressing 16 oz": [("2026-07-01", 39.80)]}

TASKS = [
    ("2026-11-05", "ValueMart", [("Pizza Sauce 1 gal", 30), ("BBQ Sauce 18 oz", 20)]),
    ("2026-11-05", "FreshCart", [("Ranch Dressing 16 oz", 10), ("Pizza Sauce 1 gal", 12)]),
    ("2026-10-25", "Lakeside Grocers", [("Pizza Sauce 1 gal", 5), ("BBQ Sauce 18 oz", 5)]),
    ("2026-11-12", "ValueMart", [("BBQ Sauce 18 oz", 40)]),
    ("2026-10-30", "Prairie Foods", [("Pizza Sauce 1 gal", 8), ("Ranch Dressing 16 oz", 4)]),
    ("2026-11-03", "Oakwood Market", [("Pizza Sauce 1 gal", 15)]),
    ("2026-11-20", "ValueMart", [("Ranch Dressing 16 oz", 20), ("BBQ Sauce 18 oz", 10)]),
    ("2026-10-28", "FreshCart", [("BBQ Sauce 18 oz", 12)]),
    ("2026-11-07", "Lakeside Grocers", [("Pizza Sauce 1 gal", 20), ("BBQ Sauce 18 oz", 20), ("Ranch Dressing 16 oz", 20)]),
    ("2026-11-01", "Prairie Foods", [("Pizza Sauce 1 gal", 10)]),
]

BASE = "You are the quote-writing AI in Sales Support at Yummy Tummy Foods. Using the price list, write the quote to send to the customer. For every item, write quantity · unit price · amount in a table."
SYMPTOM = """
[Last time's corrections from the team lead - noted word for word]
- "Pizza sauce isn't $73.40, it's $79.30. Fix it."
- "Don't write 'plus tax' on the amounts."
- "You left out the quote validity period. Add it.\""""
CAUSE = """
[Quote rules - the causes behind last time's corrections]
1. Unit price: for each item, use the price-list row with the latest effective date that is on or before the quote date. Never use a row that takes effect later.
   (Last time's cause: the first row was used without looking at the effective date)
2. Our prices include tax. Write '(tax included)' next to the amounts, and don't add tax separately.
3. Quote validity = quote date + 14 days. Write 'Valid until: YYYY-MM-DD' at the bottom of the quote."""
COND = {"A": BASE, "B": BASE + SYMPTOM, "C": BASE + CAUSE, "D": BASE + CAUSE}

MONEY = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")


def expected_price(item, day):
    rows = [p for d, p in HIST[item] if d <= day]
    return rows[-1]


def check(task, rep):
    day, cust, items = task
    fails = []
    price_ok = 0
    for item, qty in items:
        want = expected_price(item, day)
        key = item.split()[0].lower()
        lines = [l for l in rep.splitlines() if key in l.lower()]
        nums = {round(float(x.replace(",", "")), 2) for l in lines for x in MONEY.findall(l)}
        if want in nums and not ({p for _, p in HIST[item]} - {want}) & nums:
            price_ok += 1
        else:
            fails.append("unit price: %s" % item)
    vat = bool(re.search(r"tax included|incl(uding|usive of|\.)? tax|includes tax", rep, re.I)) and \
        not re.search(r"plus tax|excl(uding|usive of|\.)? tax|tax (not included|extra|additional)|\+ ?tax|sales tax[^\n]{0,20}\$?\d", rep, re.I)
    if not vat:
        fails.append("tax wording")
    vd = dt.date.fromisoformat(day) + dt.timedelta(days=14)
    forms = [vd.isoformat(), vd.strftime("%B %d, %Y"), vd.strftime("%B %d %Y"), vd.strftime("%b %d, %Y"), "%d/%d/%d" % (vd.month, vd.day, vd.year),
             "%02d/%02d/%d" % (vd.month, vd.day, vd.year), vd.strftime("%d %B %Y"), vd.strftime("%B ") + str(vd.day) + ", " + str(vd.year)]
    m = re.search(r"valid[^\n]*", rep, re.I)
    valid = bool(m) and any(f.lower() in m.group(0).lower() for f in forms)
    if not valid:
        fails.append("validity")
    return dict(price_ok=price_ok, n_items=len(items), vat=vat, valid=valid, fails=fails, ok=not fails)


def ask(sysmsg, user, extra=None):
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}] + (extra or [])
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=0.7)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + 3 * k)
    raise RuntimeError("API failed")


def run(cond, ti, trial):
    task = TASKS[ti]
    day, cust, items = task
    user = "%s\n\nQuote date: %s\nCustomer: %s\nItems: %s\nWrite the quote." % (PRICES, day, cust, ", ".join("%s x %d cases" % (i, q) for i, q in items))
    rep, tok = ask(COND[cond], user)
    first = check(task, rep)
    retried = False
    if cond == "D" and not first["ok"]:
        # the checker names the broken rule only - it never gives the right value
        msg = "Checker result - rule violations: " + ", ".join(first["fails"]) + ". Re-check the quote rules and rewrite the quote."
        rep2, tok2 = ask(COND[cond], user, [{"role": "assistant", "content": rep}, {"role": "user", "content": msg}])
        rep, tok, retried = rep2, tok + tok2, True
    g = check(task, rep)
    return dict(cond=cond, task=ti, trial=trial, report=rep, tokens=tok, retried=retried, first_ok=first["ok"], **g)


def summary(rs):
    for c in "ABCD":
        x = [r for r in rs if r["cond"] == c]
        if not x:
            continue
        old = [r for r in x if TASKS[r["task"]][0] < "2026-11-01"]
        print(c, "perfect %d/%d" % (sum(r["ok"] for r in x), len(x)),
              "| prices right %d/%d" % (sum(r["price_ok"] for r in x), sum(r["n_items"] for r in x)),
              "| October quotes (old price) right %d/%d" % (sum(r["price_ok"] for r in old), sum(r["n_items"] for r in old)),
              "| tax wording %d" % sum(r["vat"] for r in x), "| validity %d" % sum(r["valid"] for r in x),
              "| (D: perfect before the checker %d)" % sum(r["first_ok"] for r in x) if c == "D" else "",
              "| tokens %d" % (sum(r["tokens"] for r in x) / len(x)))


if __name__ == "__main__":
    conds = sys.argv[1:] or list(COND)
    jobs = [(c, t, k) for c in conds for t in range(len(TASKS)) for k in range(TRIALS)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda a: run(*a), jobs))
    out = os.path.join(HERE, "results.json")
    old = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    old = [r for r in old if r["cond"] not in conds] + res
    json.dump(old, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summary(old)
