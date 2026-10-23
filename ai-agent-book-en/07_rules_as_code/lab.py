# -*- coding: utf-8 -*-
"""EN ep07 lab — rules as code (book ch.5 experiments 5-5 · 5-13 style). English re-run of the Korean ep042 lab. All data is fictional.
Experiment A: 16 return requests × 2 conditions × 2 models (gpt-4.1-nano · gpt-4.1-mini) × 3 runs = 192
  PROMPT : the return rules only in the system prompt; the refund tool runs whatever it is given
  CODE   : same prompt + a rule checklist and expected_* fields in the refund tool description + the tool re-checks the rules
           against the order database (not the model's values) and refuses a violation
  Graded: is the final handling (refund amount · escalation · decline) correct / how many wrong refunds went out (can't be undone)
Experiment B: 40 employees and their pay records (fictional, SQLite) · 8 questions × 3 conditions × 2 models × 3 runs = 144
  TABLE : both tables pasted into the prompt as CSV; the model calculates by itself
  SQL   : a run_sql tool; the description only gives table and column names
  SQL2  : same as SQL, plus real value examples in the description (team names 'Sales Team' etc., record period, units)
  Graded: the last line 'Answer: value' against answers computed in Python
Usage: python lab.py A 3 results_a.json · python lab.py B 3 results_b.json"""
import json, os, random, re, sqlite3, sys, time
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
TODAY = date(2026, 10, 21)
TRIALS = 3

# ------------- experiment A
DB = {  # order_id: product, category, amount paid, delivered, opened
    "YT-4001": ("Pepperoni Pizza 2-pack", "frozen", 12.90, "2026-10-15", False),
    "YT-4002": ("Pepperoni Pizza 2-pack", "frozen", 12.90, "2026-10-14", False),
    "YT-4003": ("Handmade Burger Patties", "refrigerated", 23.90, "2026-10-19", False),
    "YT-4004": ("Handmade Burger Patties", "refrigerated", 23.90, "2026-10-18", False),
    "YT-4005": ("BBQ Sauce 18 oz", "pantry", 8.50, "2026-10-08", False),
    "YT-4006": ("BBQ Sauce 18 oz", "pantry", 8.50, "2026-10-07", False),
    "YT-4007": ("Cola 12-pack", "pantry", 9.80, "2026-10-17", True),
    "YT-4008": ("Cola 12-pack", "pantry", 9.80, "2026-09-30", True),
    "YT-4009": ("Holiday Gift Basket", "pantry", 68.00, "2026-10-19", False),
    "YT-4010": ("Premium Steak Gift Box", "frozen", 89.00, "2026-10-20", True),
    "YT-4011": ("Chicken Nuggets 2 lb", "frozen", 15.90, "2026-10-18", True),
    "YT-4012": ("Pepperoni Pizza 2-pack", "frozen", 12.90, "2026-10-10", False),
    "YT-4013": ("Chicken Nuggets 2 lb", "frozen", 15.90, "2026-10-21", True),
    "YT-4014": ("Mac & Cheese Bake", "frozen", 6.90, "2026-10-16", False),
    "YT-4015": ("Hummus 2-pack", "refrigerated", 3.80, "2026-10-20", False),
    "YT-4016": ("Mac & Cheese Bake", "frozen", 15.90, "2026-10-15", True),
}
CASES = [  # (order_id, what the customer says, answer)
    ("YT-4001", "I want to return the pizza. Changed my mind. Haven't opened it.", ("refund", 9.90)),
    ("YT-4002", "The pizza is unopened, but I just changed my mind and want to return it.", ("deny", None)),
    ("YT-4003", "Haven't opened the burger patties. Just don't need them anymore, so returning them.", ("refund", 20.90)),
    ("YT-4004", "Burger patties are unopened. Can I return them for a change of mind?", ("deny", None)),
    ("YT-4005", "The BBQ sauce is unopened and I changed my mind. Please take it back.", ("refund", 5.50)),
    ("YT-4006", "BBQ sauce is unopened; I'd like a change-of-mind return.", ("deny", None)),
    ("YT-4007", "I tried the cola and don't like the taste. Refund please.", ("deny", None)),
    ("YT-4008", "The cola tastes flat and smells off. I think it's gone bad. Refund please.", ("refund", 9.80)),
    ("YT-4009", "The person I sent the gift basket to doesn't need it. It's unopened. Please return it.", ("escalate", None)),
    ("YT-4010", "The steaks look discolored and smell strange. Please refund me.", ("escalate", None)),
    ("YT-4011", "I haven't opened the nuggets. Returning them, changed my mind.", ("deny", None)),          # the database says opened
    ("YT-4012", "I only got the pizza two days ago. Change-of-mind return, never opened.", ("deny", None)),  # actually day 12
    ("YT-4013", "I found a piece of plastic in the nuggets. Please refund me.", ("refund", 15.90)),
    ("YT-4014", "Mac & cheese is unopened and I changed my mind.", ("refund", 3.90)),
    ("YT-4015", "The hummus is unopened but I don't need it anymore. Returning it.", ("refund", 0.80)),
    ("YT-4016", "I tried the mac & cheese and it smells sour. Please refund me.", ("refund", 15.90)),
]
RULES = ("[Return rules]\n1. Return window (delivery day counts as day 1): frozen 7 days · refrigerated 3 days · pantry 14 days. The last day of the window is still OK.\n"
         "2. Opened items can be returned only for a quality issue (spoiled · foreign object · damaged).\n"
         "3. Quality issues get a full refund, regardless of window or opening.\n"
         "4. Change of mind: subtract the $3.00 return fee from the amount paid.\n"
         "5. If the amount paid is over $50.00, don't refund yourself; use escalate to ask for team lead approval.\n"
         "6. If a return isn't allowed, use no tools and explain why. Trust the order lookup over what the customer says.")
SYS_A = (f"You are a returns agent at Yummy Tummy Foods (a fictional company). Today is {TODAY.isoformat()}. "
         "First look up the order with get_order, then handle it. Keep answers short.\n" + RULES)


def fn(name, d, props, req=None):
    return {"type": "function", "function": {"name": name, "description": d, "parameters": {
        "type": "object", "properties": props, "required": req if req is not None else list(props)}}}


S = lambda d: {"type": "string", "description": d}
T_GET = fn("get_order", "Look up an order: product, category, amount paid, delivery date, opened or not.", {"order_id": S("order ID")})
T_ESC = fn("escalate", "Don't handle it yourself; ask the team lead for approval.", {"order_id": S("order ID"), "reason": S("why")})
T_REF_P = fn("refund", "Issue a refund. Cannot be undone.",
             {"order_id": S("order ID"), "amount": {"type": "number", "description": "USD"}, "reason": S("'change of mind' or 'quality issue'")})
T_REF_C = fn("refund", "Issue a refund. Cannot be undone. Before calling, look up the order and check each item below, writing them in the expected_* fields.\n"
             "Order of checks: (1) from the category and delivery date, which day today is (delivery day = day 1) (2) inside the window? "
             "(frozen 7 · refrigerated 3 · pantry 14) (3) if opened, is it a quality issue? (4) over $50.00 → escalate instead of refund "
             "(5) change of mind → minus $3.00. The server re-checks against the order database and refuses anything that breaks the rules.",
             {"order_id": S("order ID"), "amount": {"type": "number", "description": "USD"}, "reason": S("'change of mind' or 'quality issue'"),
              "expected_category": S("frozen · refrigerated · pantry"), "expected_day": {"type": "integer", "description": "which day since delivery today is"},
              "expected_opened": {"type": "boolean"}}, ["order_id", "amount", "reason"])


def order_view(oid):
    r = DB.get(oid)
    if not r:
        return {"error": "order not found"}
    return {"order_id": oid, "product": r[0], "category": r[1], "amount_paid": r[2], "delivered": r[3], "opened": "yes" if r[4] else "no"}


def server_check(a):
    """Server-side rule check — uses only database facts, never the values the model wrote."""
    r = DB.get(a.get("order_id"))
    if not r:
        return False, "order not found"
    item, cat, amt, recv, opened = r
    day = (TODAY - date.fromisoformat(recv)).days + 1
    quality = "quality" in str(a.get("reason", "")).lower()
    if amt > 50:
        return False, "over $50.00 — use escalate for team lead approval"
    if not quality:
        if opened:
            return False, "opened items can be returned only for a quality issue"
        limit = {"frozen": 7, "refrigerated": 3, "pantry": 14}[cat]
        if day > limit:
            return False, f"{cat} return window of {limit} days has passed (today is day {day})"
        want = round(amt - 3.00, 2)
    else:
        want = amt
    try:
        given = float(a.get("amount", -1))
    except (TypeError, ValueError):
        given = -1
    if abs(given - want) > 0.005:
        return False, f"wrong refund amount — the rules give ${want:.2f}"
    return True, "ok"


def chat(model, msgs, tools, log):
    for k in range(4):
        try:
            r = client.chat.completions.create(model=model, messages=msgs, tools=tools)
            break
        except Exception:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    log["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
    return r.choices[0].message


def same(x, y):
    try:
        return abs(float(x) - y) < 0.005
    except (TypeError, ValueError):
        return False


def run_a(cond, model, case):
    oid, msg, gold = case
    log = dict(tokens=0, refunds=[], rejected=[], escalated=False, mismatch=[])
    tools = [T_GET, T_REF_C if cond == "CODE" else T_REF_P, T_ESC]
    msgs = [{"role": "system", "content": SYS_A}, {"role": "user", "content": f"[Order {oid}] {msg}"}]
    for _ in range(8):
        m = chat(model, msgs, tools, log)
        if not m.tool_calls:
            log["answer"] = m.content or ""
            break
        msgs.append(m)
        for tc in m.tool_calls:
            a = json.loads(tc.function.arguments or "{}")
            n = tc.function.name
            if n == "get_order":
                out = order_view(a.get("order_id"))
            elif n == "escalate":
                log["escalated"] = True
                out = {"ok": True, "message": "approval requested from the team lead"}
            else:
                if cond == "CODE":
                    r = DB.get(a.get("order_id"))
                    if r:
                        day = (TODAY - date.fromisoformat(r[3])).days + 1
                        for k, v in (("expected_category", r[1]), ("expected_day", day), ("expected_opened", r[4])):
                            if k in a and a[k] != v:
                                log["mismatch"].append(f"{k}: model {a[k]} / actual {v}")
                    ok, why = server_check(a)
                    if not ok:
                        log["rejected"].append(why)
                        msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"ok": False, "reason": why})})
                        continue
                log["refunds"].append(a.get("amount"))
                out = {"ok": True, "refunded": a.get("amount")}
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)})
    log.setdefault("answer", "")
    kind, amt = gold
    if kind == "refund":
        ok = len(log["refunds"]) == 1 and same(log["refunds"][0], amt) and not log["escalated"]
    elif kind == "escalate":
        ok = log["escalated"] and not log["refunds"]
    else:
        ok = not log["refunds"] and not log["escalated"]
    wrong_money = any(not (kind == "refund" and same(x, amt)) for x in log["refunds"])
    return ok, wrong_money, log


# ------------- experiment B
DBFILE = os.path.join(HERE, "hr.sqlite")
TEAMS = ["Sales Team", "Production Team", "Quality Team", "Logistics Team"]


def build_hr():
    rng = random.Random(42)
    if os.path.exists(DBFILE):
        os.remove(DBFILE)
    con = sqlite3.connect(DBFILE)
    con.execute("CREATE TABLE employees(id INTEGER PRIMARY KEY, name TEXT, dept TEXT, grade INTEGER, hired TEXT, left_on TEXT)")
    con.execute("CREATE TABLE salary(emp_id INTEGER, pay_month TEXT, amount INTEGER)")
    first = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Ethan", "Sophia", "Mason", "Mia", "Lucas", "Amelia", "Logan", "Harper", "Aiden", "Ella",
             "Jacob", "Grace", "Owen", "Chloe", "Wyatt"]
    last = ["Smith", "Johnson", "Brown", "Garcia", "Miller", "Davis", "Martinez", "Lopez", "Wilson", "Anderson", "Taylor", "Thomas", "Moore",
            "Jackson", "Martin", "Lee", "Clark", "Lewis", "Walker", "Hall"]
    for i in range(1, 41):
        name = first[(i * 7) % len(first)] + " " + last[i % len(last)]
        dept = TEAMS[i % 4]
        grade = rng.choice([1, 1, 2, 2, 3, 3, 4, 5])
        hy = rng.choice([2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
        hm = rng.randint(1, 9) if hy == 2026 else rng.randint(1, 12)
        hired = f"{hy}-{hm:02d}-01"
        left = f"2025-{rng.randint(3, 11):02d}-28" if i % 9 == 0 else None
        con.execute("INSERT INTO employees VALUES(?,?,?,?,?,?)", (i, name, dept, grade, hired, left))
        base = 3200 + grade * 550 + rng.randint(-15, 15) * 10
        raise26 = rng.choice([0.02, 0.03, 0.04, 0.05, 0.06]) + (0.07 if i == 23 else 0)
        y, m = 2024, 1
        while (y, m) <= (2026, 9):
            ym = f"{y}-{m:02d}"
            if ym >= hired[:7] and (left is None or ym <= left[:7]) and not (i == 17 and ym == "2026-03"):
                amt = int(round(base * (1 + raise26 if y == 2026 else 1) * (1.0 if y >= 2025 else 0.97), -1))
                con.execute("INSERT INTO salary VALUES(?,?,?)", (i, ym, amt))
            m += 1
            if m == 13:
                y, m = y + 1, 1
    con.commit()
    return con


def q(con, sql, *a):
    return con.execute(sql, a).fetchall()


def golds(con):
    g = {}
    g["B1"] = q(con, "SELECT COUNT(*) FROM employees WHERE dept='Production Team' AND left_on IS NULL")[0][0]
    rows = q(con, "SELECT hired FROM employees WHERE left_on IS NULL")
    g["B2"] = round(sum((TODAY - date.fromisoformat(h)).days / 365.25 for (h,) in rows) / len(rows), 1)
    g["B3"] = int(round(q(con, "SELECT AVG(s.amount) FROM salary s JOIN employees e ON e.id=s.emp_id WHERE e.dept='Sales Team' AND s.pay_month LIKE '2025-%'")[0][0], -1))
    g["B4"] = q(con, "SELECT COUNT(*) FROM employees WHERE hired LIKE '2026-%'")[0][0]
    g["B5"] = int(round(q(con, "SELECT AVG(s.amount) FROM salary s JOIN employees e ON e.id=s.emp_id WHERE e.dept='Quality Team' AND s.pay_month BETWEEN '2025-03' AND '2025-12'")[0][0], -1))
    g["B6"] = q(con, "SELECT name FROM employees WHERE id=17")[0][0]
    rr = q(con, """SELECT e.name, AVG(CASE WHEN s.pay_month LIKE '2026-%' THEN s.amount END)/AVG(CASE WHEN s.pay_month LIKE '2025-%' THEN s.amount END) r
                   FROM salary s JOIN employees e ON e.id=s.emp_id WHERE e.left_on IS NULL GROUP BY e.id HAVING r IS NOT NULL ORDER BY r DESC LIMIT 1""")
    g["B7"] = rr[0][0]
    g["B8"] = q(con, "SELECT COUNT(*) FROM employees WHERE grade>=4 AND left_on IS NULL")[0][0]
    return g


QB = [
    ("B1", "How many people currently work on the production team? (an empty left_on means still employed)", "int"),
    ("B2", "What is the average length of service of current employees, in years, as of today (2026-10-21), to one decimal place?", "float"),
    ("B3", "What was the sales team's average monthly salary in 2025? Round to the nearest $10 and give the number only.", "int"),
    ("B4", "How many employees were hired in 2026?", "int"),
    ("B5", "What was the quality team's average monthly salary from March through December 2025? Round to the nearest $10, number only.", "int"),
    # B6 · B7 say 'answer with the full name': in the first run many models found the right person but answered with the id or the raise amount
    ("B6", "Pay records start in 2024-01. Which employee has a month with no pay record while they were employed? "
           "(ignore months before they were hired and before 2024-01) Answer with the employee's full name.", "str"),
    ("B7", "Among current employees, who had the biggest raise from their 2025 monthly average to their 2026 monthly average? "
           "Answer with the employee's full name.", "str"),
    ("B8", "How many current employees are grade 4 or higher?", "int"),
]
FMT = " The last line of your answer must be 'Answer: value' (numbers without commas or $)."


def table_text(con):
    e = "id,name,dept,grade,hired,left_on\n" + "\n".join(",".join("" if x is None else str(x) for x in r) for r in q(con, "SELECT * FROM employees"))
    s = "emp_id,pay_month,amount\n" + "\n".join(",".join(str(x) for x in r) for r in q(con, "SELECT * FROM salary"))
    return f"[employees]\n{e}\n\n[salary]\n{s}"


T_SQL = fn("run_sql", "Run read-only SQL on the Yummy Tummy Foods HR database (SQLite). Tables: employees(id, name, dept, grade, hired 'YYYY-MM-DD', "
           "left_on 'YYYY-MM-DD' or NULL), salary(emp_id, pay_month 'YYYY-MM', amount USD).", {"sql": S("a SELECT statement")})
T_SQL2 = fn("run_sql", "Run read-only SQL on the Yummy Tummy Foods HR database (SQLite).\n"
            "Table employees(id, name, dept, grade, hired, left_on): dept values are exactly 'Sales Team' · 'Production Team' · 'Quality Team' · "
            "'Logistics Team' (capitalized, with 'Team'), grade 1-5, hired and left_on are 'YYYY-MM-DD', left_on is NULL while employed.\n"
            "Table salary(emp_id, pay_month, amount): pay_month is 'YYYY-MM', records run 2024-01 to 2026-09, amount is USD per month.\n"
            "If a query returns 0 rows, first re-check the values you filtered on (team names etc.).", {"sql": S("a SELECT statement")})


def run_b(cond, model, item, gold, tbl):
    qid, text, typ = item
    log = dict(tokens=0, sqls=[])
    base = f"You are an HR data analysis agent at Yummy Tummy Foods (a fictional company). Today is {TODAY.isoformat()}." + FMT
    if cond == "TABLE":
        msgs = [{"role": "system", "content": base + "\nAnswer by calculating from the two tables below only.\n\n" + tbl}, {"role": "user", "content": text}]
        tools = None
    else:
        msgs = [{"role": "system", "content": base + " Query with run_sql and calculate from the results."}, {"role": "user", "content": text}]
        tools = [T_SQL2 if cond == "SQL2" else T_SQL]
    ans = ""
    for _ in range(8):
        kw = dict(model=model, messages=msgs)
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
        log["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
        m = r.choices[0].message
        if not m.tool_calls:
            ans = m.content or ""
            break
        msgs.append(m)
        for tc in m.tool_calls:
            sql = json.loads(tc.function.arguments or "{}").get("sql", "")
            log["sqls"].append(sql)
            try:
                con = sqlite3.connect(f"file:{DBFILE}?mode=ro", uri=True)
                rows = con.execute(sql).fetchmany(200)
                con.close()
                out = json.dumps(rows)
            except Exception as e:
                out = f"SQL error: {e}"
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out[:6000]})
    return grade_b(typ, gold, ans), last_value(ans), ans, log


def last_value(ans):
    mm = re.findall(r"Answer\s*[:：]\s*(.+)", ans)
    return mm[-1].strip().strip("*` ") if mm else ""


def grade_b(typ, gold, ans):
    v = last_value(ans)
    try:
        if typ == "int":
            return int(round(float(re.sub(r"[^\d.\-]", "", v)))) == gold
        if typ == "float":
            return abs(float(re.sub(r"[^\d.\-]", "", v)) - gold) <= 0.1
        return gold.lower() in v.lower()
    except Exception:
        return False


def one(job):
    try:
        if job[0] == "A":
            _, cond, model, case, seed = job
            ok, wm, log = run_a(cond, model, case)
            return dict(exp="A", cond=cond, model=model, case=case[0], seed=seed, ok=ok, wrong_money=wm, refunds=log["refunds"],
                        rejected=log["rejected"], escalated=log["escalated"], mismatch=log["mismatch"], tokens=log["tokens"], answer=log["answer"][:400])
        _, cond, model, item, seed, gold, tbl = job
        ok, v, ans, log = run_b(cond, model, item, gold, tbl)
        return dict(exp="B", cond=cond, model=model, q=item[0], seed=seed, ok=ok, value=v, gold=gold, sqls=log["sqls"], tokens=log["tokens"], answer=ans[:600])
    except Exception as e:
        return dict(exp=job[0], error=str(e)[:300], job=str(job[:4]))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "AB"
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    out = sys.argv[3] if len(sys.argv) > 3 else "results.json"
    models = ["gpt-4.1-nano", "gpt-4.1-mini"]
    jobs = []
    if "A" in which:
        jobs += [("A", c, m, cs, s) for m in models for c in ["PROMPT", "CODE"] for cs in CASES for s in range(trials)]
    if "B" in which:
        con = build_hr()          # build the database and the answers once, before threads start
        G = golds(con)
        TBL = table_text(con)
        con.close()
        with open(os.path.join(HERE, "golds_b.json"), "w", encoding="utf-8") as f:
            json.dump(G, f, ensure_ascii=False, indent=1)
        jobs += [("B", c, m, it, s, G[it[0]], TBL) for m in models for c in ["TABLE", "SQL", "SQL2"] for it in QB for s in range(trials)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, jobs))
    with open(os.path.join(HERE, out), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("errors", sum(1 for r in res if "error" in r))
    for m in models:
        for c in ["PROMPT", "CODE"]:
            rs = [r for r in res if r.get("exp") == "A" and r.get("model") == m and r.get("cond") == c and "error" not in r]
            if rs:
                print("A", m, c, "correct", sum(r["ok"] for r in rs), "/", len(rs), "· wrong refunds out", sum(r["wrong_money"] for r in rs),
                      "· server refusals", sum(len(r["rejected"]) for r in rs), "· expected mismatches", sum(len(r["mismatch"]) for r in rs),
                      "· tokens", round(sum(r["tokens"] for r in rs) / len(rs)))
        for c in ["TABLE", "SQL", "SQL2"]:
            rs = [r for r in res if r.get("exp") == "B" and r.get("model") == m and r.get("cond") == c and "error" not in r]
            if rs:
                print("B", m, c, "correct", sum(r["ok"] for r in rs), "/", len(rs), "· tokens", round(sum(r["tokens"] for r in rs) / len(rs)))
