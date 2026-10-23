# -*- coding: utf-8 -*-
"""EN es01 lab — Outcomes before output (source: AI Engineering from Scratch, Phase 14 lesson 47, the 6-box outcome frame).
English re-run of the Korean 01_outcome_first with the same design and the same numbers, US grocery items and USD.
Yummy Tummy Foods (fictional) logistics: 26 inventory items as of Mon 2026-10-26. 6 items run out before their next delivery (the answer key).
Conditions (gpt-4.1-mini, 10 runs each):
  A output only        : "Make me a weekly inventory report"
  B output + polish    : A + "for the team lead, thorough and nice to look at"
  D ask first          : A + "feel free to ask first" -> a team-lead model answers only what was asked, then the report
  C outcome frame      : User / Situation / Current way / Desired outcome / Constraints / Non-goals (6 boxes)
  E frame + how to check : C + "days of cover and days until delivery side by side; shorter = STOCKOUT RISK" (the lesson's evidence question)
  F E + math in code   : E + "write Python that prints the report" -> the code is actually run (errors sent back, up to 3 tries)
Grading (code): risky items found (6) / false flags / unit cost leaked / non-goals mixed in (sales, charts, expiry) / length.
  'flagged' = the item name is on a line with a risk word (lines that negate it - 'no risk', 'sufficient' - don't count). test_grade.py first.
Usage: python lab.py [A B C D E F]   (TRIALS env var, default 10)"""
import datetime as dt, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))
TODAY = dt.date(2026, 10, 26)

# code, item, DC, on hand (cases), avg daily shipments (cases), next delivery, unit cost ($/case), expiring within 30 days (cases)
# Same numbers as the Korean run, so the traps are identical: big numbers that still run out (F103, D307), small numbers that are safe (C201, C204, M403).
ROWS = [
    ("F101", "Pepperoni Pizza 2-pack", "Dayton", 0, 85, "10-28", 41.20, 0),
    ("F102", "Cheese Pizza 2-pack", "Dayton", 40, 38, "10-29", 38.90, 0),
    ("F103", "Chicken Nuggets 2 lb", "Dayton", 610, 72, "11-05", 52.30, 12),
    ("F104", "Shrimp Fried Rice Bowl", "Dayton", 220, 20, "11-02", 44.80, 0),
    ("F105", "Mozzarella Sticks 2 lb", "Dayton", 95, 9, "10-30", 61.50, 0),
    ("C201", "Fresh Salsa 16 oz", "Columbus", 180, 64, "10-27", 16.80, 40),
    ("C202", "Fresh Pasta 1 lb", "Columbus", 300, 55, "11-03", 22.40, 25),
    ("C203", "Hummus 2-pack", "Columbus", 130, 15, "10-31", 33.60, 0),
    ("C204", "Handmade Burger Patties", "Columbus", 90, 40, "10-27", 27.90, 10),
    ("C205", "Greek Yogurt 4-pack", "Columbus", 260, 30, "11-01", 17.50, 30),
    ("D301", "BBQ Sauce 18 oz", "Chicago", 600, 35, "11-09", 46.20, 0),
    ("D302", "Ranch Dressing 16 oz", "Chicago", 210, 12, "11-06", 39.80, 0),
    ("D303", "Ketchup 32 oz", "Chicago", 190, 22, "11-02", 54.10, 0),
    ("D304", "Olive Oil 500 ml", "Chicago", 400, 18, "11-12", 88.60, 0),
    ("D305", "Pizza Sauce 1 gal", "Chicago", 55, 4, "11-05", 73.40, 0),
    ("D306", "Sesame Burger Buns 8-pack", "Chicago", 700, 60, "11-05", 25.20, 0),
    ("D307", "Cola 12-pack", "Chicago", 1500, 140, "11-07", 19.80, 0),
    ("D308", "Canola Oil 1 gal", "Chicago", 160, 25, "10-31", 49.90, 0),
    ("M401", "Mac & Cheese Bake Kit", "Dayton", 100, 11, "11-02", 58.70, 8),
    ("M402", "Chicken Pot Pie Kit", "Dayton", 150, 26, "11-04", 64.30, 0),
    ("M403", "Taco Night Kit", "Dayton", 60, 12, "10-29", 57.20, 6),
    ("M404", "Shrimp Scampi Kit", "Dayton", 250, 14, "11-09", 69.90, 0),
    ("S501", "Holiday Gift Basket", "Chicago", 330, 6, "11-20", 95.00, 0),
    ("S502", "Snack Gift Box", "Chicago", 140, 8, "11-09", 72.00, 0),
    ("S503", "Premium Steak Gift Box", "Chicago", 70, 7, "11-02", 81.50, 0),
    ("S504", "Hot Cocoa Gift Tin", "Chicago", 500, 9, "11-25", 99.00, 0),
]


def arrive_days(a):
    return (dt.date(2026, int(a[:2]), int(a[3:])) - TODAY).days


RISK = {r[0] for r in ROWS if r[3] / r[4] < arrive_days(r[5])}
for r in ROWS:   # no borderline items: cover vs. delivery differ by at least a day
    assert abs(r[3] / r[4] - arrive_days(r[5])) >= 1, r

TABLE = "As of: 2026-10-26 (Mon)\nCode\tItem\tDC\tOn hand (cases)\tAvg daily shipments (cases)\tNext delivery\tUnit cost ($/case)\tExpiring within 30 days (cases)\n" + \
        "\n".join("\t".join(("%.2f" % x) if isinstance(x, float) else str(x) for x in r) for r in ROWS)

REQ = "Here's this week's inventory data. Make me a weekly inventory report from it.\n\n" + TABLE
POLISH = "\n\nIt's for the team lead, so make it thorough and nice to look at."
FRAME = """Here's this week's inventory data. Put it together following the frame below.

[User] Logistics team lead
[Situation] The Monday 9 am ordering meeting, every week. The report goes up on the meeting screen, and the carrier's account rep sits in too.
[Current way] The team lead scans the 26 rows in Excel and works out the dates by hand. It takes about 20 minutes, and things slip through (last month we ran out of pepperoni pizza).
[Desired outcome] Within the first 5 minutes of the meeting, know every item that will run out before its next delivery, and decide the orders.
[Constraints] Unit costs must not appear in the meeting material (the carrier rep sees it). One screen's worth.
[Non-goals] Sales analysis, charts, expiry management (handled in a separate meeting).

""" + TABLE
EVID = FRAME.replace("[Non-goals]", "[How to check] So the team lead can verify it right in the meeting, show for every item 'days of cover (on hand / avg daily shipments)' and 'days until next delivery' side by side, mark every item whose days of cover is the shorter number as 'STOCKOUT RISK', and group those at the top.\n[Non-goals]")
ASK = REQ + "\n\nIf there's anything you really need to know before you start, feel free to ask first."
MANAGER = """You are the logistics team lead at Yummy Tummy Foods. The AI asked questions before writing the report. Answer briefly, and only what it asked, from the facts below. Don't volunteer anything it didn't ask. If you don't know, say 'use your judgment'.
- The report goes up on the screen at the Monday 9 am ordering meeting. The carrier's account rep sits in too.
- Right now I scan the spreadsheet myself and work out the dates; it takes about 20 minutes and I sometimes miss things (last month we ran out of pepperoni pizza).
- Within the first 5 minutes of the meeting I want to know every item that will run out before its next delivery, and decide the orders.
- Unit costs must not go into the meeting material (the carrier rep sees it). One screen's worth is ideal.
- No sales analysis, charts or expiry management (that's a separate meeting)."""

CODE = EVID.replace("Here's this week's inventory data. Put it together following the frame below.",
    "Here's this week's inventory data. Build a report that follows the frame below. Don't do the date and division math yourself: write Python code that prints the report. The data is given as a variable DATA (a tab-separated string exactly like the table below; the first line is the as-of date). Answer with a single code block only.")
COND = {"A": REQ, "B": REQ + POLISH, "C": FRAME, "D": ASK, "E": EVID, "F": CODE}

# risk words (regex, case-insensitive). 'low' alone is not a risk word: 'low but arriving tomorrow' is a safe statement.
RISK_RE = re.compile(r"stock[- ]?out|out of stock|run(s|ning)? out|depleted|shortage|shortfall|short(?!er| of (the )?(expir|list|report))|at risk|risk|urgent|critical|"
                     r"reorder|re-order|order now|needs? (an )?order|insufficient|will not last|won't last|not enough|before (the )?next delivery|zero stock|no stock|\|\s*yes\s*\|", re.I)
# '| NO |' = a 'Needs order?' table cell saying no; 'no immediate' = 'monitor, no immediate order needed' (added after reading the C reports - see NOTES)
SAFE_RE = re.compile(r"no risk|not at risk|safe|sufficient|enough|adequate|healthy|\bok\b|\bfine\b|no action|covered|no issue|not needed|unnecessary|stable|comfortable|"
                     r"will last|lasts? until|no (stockout|shortage|concern)|low[- ]risk|\|\s*no\s*\||no immediate", re.I)
HARD_RE = re.compile(r"stock[- ]?out|out of stock|run(s|ning)? out|depleted|zero stock|no stock|\b0 cases", re.I)
EXPIRY_RE = re.compile(r"expir|shelf[- ]life|best[- ]by", re.I)
NONGOAL = {"sales": re.compile(r"revenue|sales (analysis|trend|performance|figures|growth|forecast)|top[- ]sell|best[- ]sell", re.I),
           "chart": re.compile(r"\bchart|\bgraph", re.I),
           "expiry": EXPIRY_RE}
NEGATE_RE = re.compile(r"exclud|not includ|separate|out of scope|non-goal|omit|not cover|skip|not part|left out|no (charts?|graphs?)", re.I)


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception as e:
            time.sleep(3 + k * 3)
    raise RuntimeError("API failed")


SIZE = re.compile(r"\s*\d+(\.\d+)?\s*(oz|lb|ml|gal|-pack|pack)\b", re.I)
CORE = {r[0]: SIZE.sub("", r[1]).strip().lower() for r in ROWS}


def items_in(line):
    t = line.lower()
    return {c for c in CORE if c in line or CORE[c] in t}


def is_risky(line):
    if not RISK_RE.search(line):
        return False
    rest = HARD_RE.sub("", line)
    if SAFE_RE.search(rest) and not HARD_RE.search(line):
        return False      # 'no risk', 'stock is sufficient'
    if EXPIRY_RE.search(line) and not (HARD_RE.search(line) or re.search(r"before (the )?next delivery", line, re.I)):
        return False      # an expiry warning is not a stockout flag
    return True


def is_head(line):
    s = line.strip().rstrip(":").strip()
    return line.strip().startswith("#") or (s.startswith("**") and s.endswith("**")) or line.strip().endswith(":") \
        or re.match(r"^\d+\.\s*\*\*[^*]+\*\*\s*$", s) is not None


def flagged(report):
    """Item codes the report flags as 'runs out before the next delivery' (stockout risk).
    A line counts when it carries a risk word itself, or sits under a heading that does (list / table rows)."""
    out, sec = set(), False
    for line in report.splitlines():
        its = items_in(line)
        if is_head(line) and not its:
            sec = is_risky(line)
            continue
        if not its:
            continue
        if is_risky(line) or (sec and not SAFE_RE.search(HARD_RE.sub("", line))):
            out |= its
    return out


def leaked_price(report):
    """Unit costs that appear in the report: the exact 2-decimal form (41.20) or a dollar form ($41.2).
    (First version also matched the 1-decimal form without '$' - that hit 'days of cover 17.5' and counted it as the $17.50 yogurt cost. Fixed, re-graded.)"""
    out, ctx = [], False
    for r in ROWS:
        v = r[6]
        pats = [r"(?<![\d.])%s(?![\d])" % re.escape("%.2f" % v), r"\$\s?%s(?![\d])" % re.escape(("%.2f" % v).rstrip("0").rstrip("."))]
        for line in report.splitlines():
            if any(re.search(p, line) for p in pats):
                out.append("%.2f" % v)
                if "$" in line or re.search(r"cost|price", line, re.I):
                    ctx = True
                break
    # a single bare number can be a computed value (days of cover 210/12 = 17.50 looks like the $17.50 yogurt cost):
    # count a leak only with money context on the line, or when 3+ different cost values appear (a copied column)
    return out if (ctx or len(out) >= 3) else []


NUM = re.compile(r"-?\d+(?:\.\d+)?")


def evidence_ok(report):
    """Of the 6 risky items, how many have 'days of cover' (within 0.06) and 'days until delivery' together on one line - can the lead verify it?"""
    n = 0
    for r in ROWS:
        if r[0] not in RISK:
            continue
        cover, days = r[3] / r[4], arrive_days(r[5])
        for line in report.splitlines():
            if r[0] in line or CORE[r[0]] in line.lower():
                nums = [float(x) for x in NUM.findall(line.replace(",", ""))]
                if any(abs(x - cover) < 0.06 for x in nums) and days in nums:
                    n += 1
                    break
    return n


def nongoal(report):
    out = []
    for k, rx in NONGOAL.items():
        for line in report.splitlines():
            if rx.search(line) and not NEGATE_RE.search(line):
                out.append(k)
                break
    return out


def grade(report):
    f = flagged(report)
    return dict(found=sorted(f & RISK), missed=sorted(RISK - f), false=sorted(f - RISK), price=leaked_price(report),
                nongoal=nongoal(report), evidence=evidence_ok(report), chars=len(report), words=len(report.split()))


def run(cond, i):
    t0 = time.time()
    msgs = [{"role": "user", "content": COND[cond]}]
    rep, tok = chat(msgs)
    qa = None
    if cond == "D":
        # if the first answer is a question, the team lead answers, then we get the report
        if "?" in rep[:1500] and len(rep) < 1500:
            ans, t2 = chat([{"role": "system", "content": MANAGER}, {"role": "user", "content": rep}], temp=0.3)
            msgs += [{"role": "assistant", "content": rep}, {"role": "user", "content": ans + "\n\nNow write the report."}]
            qa = dict(q=rep, a=ans)
            rep, t3 = chat(msgs)
            tok += t2 + t3
    code = None
    if cond == "F":
        # actually run the model's code and use its output as the report;
        # on an error, send the message back and let it fix the code (up to 3 runs - like a person running and fixing it)
        import subprocess, tempfile
        msgs += [{"role": "assistant", "content": rep}]
        errors = []
        for attempt in range(3):
            m = re.search(r"```(?:python)?\n(.*?)```", rep, re.S)
            code = m.group(1) if m else rep
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "report.py")
                open(f, "w", encoding="utf-8").write("DATA = " + repr(TABLE) + "\n" + code)
                try:
                    pr = subprocess.run([sys.executable, "-I", "-X", "utf8", f], capture_output=True, text=True, encoding="utf-8",
                                        errors="replace", timeout=30, cwd=d, env={"PYTHONIOENCODING": "utf-8", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})
                    ok, out = pr.returncode == 0, (pr.stdout if pr.returncode == 0 else pr.stderr[-800:])
                except subprocess.TimeoutExpired:
                    ok, out = False, "timed out"
            if ok:
                rep = out
                break
            errors.append(out)
            msgs.append({"role": "user", "content": "I ran it and got an error. Give me one corrected code block.\n" + out})
            rep, t4 = chat(msgs)
            tok += t4
            msgs.append({"role": "assistant", "content": rep})
        else:
            rep = "3 failed runs"
        qa = dict(errors=errors)
    g = grade(rep)
    return dict(cond=cond, i=i, report=rep, code=code, qa=qa, tokens=tok, sec=round(time.time() - t0, 1), **g)


def summary(rs):
    n = len(rs)
    ok = sum(1 for r in rs if not r["missed"] and not r["false"] and not r["price"])
    return ("perfect %d/%d | found %.1f/6 | false flags %d | cost leaked %d | non-goals %d | words %d | asked %d | verifiable %.1f/6 | tokens %d"
            % (ok, n, sum(len(r["found"]) for r in rs) / n, sum(len(r["false"]) for r in rs), sum(1 for r in rs if r["price"]),
               sum(1 for r in rs if r["nongoal"]), sum(r["words"] for r in rs) / n, sum(1 for r in rs if r["qa"] and r["qa"].get("q")),
               sum(r["evidence"] for r in rs) / n, sum(r["tokens"] for r in rs) / n))


if __name__ == "__main__":
    print("answer key (run out before next delivery):", sorted(RISK))
    conds = sys.argv[1:] or list(COND)
    jobs = [(c, i) for c in conds for i in range(TRIALS)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda a: run(*a), jobs))
    out = os.path.join(HERE, "results.json")
    old = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    old = [r for r in old if r["cond"] not in conds] + res
    json.dump(old, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for c in conds:
        print(c, summary([r for r in res if r["cond"] == c]))
