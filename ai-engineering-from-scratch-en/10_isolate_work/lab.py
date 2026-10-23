# -*- coding: utf-8 -*-
"""EN es10 lab — Delegate agent work with isolation and merge contracts (source: AI Engineering from Scratch, Phase 14 lesson 45).
English re-run of the Korean 10_isolate_work: three agents (prices · allergens · shipping) edit the Yummy Tummy Foods (fictional) customer product sheet at the same time. gpt-4.1-mini, 10 runs each.
  A one shared file   : 3 agents read, edit and save the whole product_sheet.md at the same time
  C ownership in words: A + "your section is X only, don't touch the others" (still one file)
  B split files       : one file per section, each agent can write only its own file (the tool refuses others) -> code stitches them in order
  S one at a time     : the same file, agents run one after another
Grading (code): do all 7 edits by the three agents survive in the final document · attempts to write someone else's file · time taken.
Parallel-run caution (lab-thread-cache lesson): the fake file system is created per run and shared only between that run's threads."""
import copy, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

SEC = {
    "price": """## 1. Price list (per case, tax included)
- Pizza Sauce 1 gal: $73.40
- BBQ Sauce 18 oz: $46.20
- Ranch Dressing 16 oz: $39.80""",
    "allergy": """## 2. Allergen labels
- Pizza Sauce 1 gal: soy, wheat
- Snack Gift Box: peanuts
- Sesame Burger Buns 8-pack: soy""",
    "ship": """## 3. Shipping and returns
- Same-day dispatch cutoff: orders by 3 pm
- Frozen returns: within 7 days of delivery
- Free shipping on orders over $50""",
}
HEAD = "# Yummy Tummy Foods - product sheet for trade customers (November 2026 edition)"
DOC = HEAD + "\n\n" + "\n\n".join(SEC[k] for k in ("price", "allergy", "ship")) + "\n"

TASK = {
    "price": "Update the price list: Pizza Sauce 1 gal to $79.30 and BBQ Sauce 18 oz to $47.50. Ranch Dressing stays the same.",
    "allergy": "Update the allergen labels: add 'walnuts, almonds' to the Snack Gift Box, and add 'sesame' to the Sesame Burger Buns 8-pack.",
    "ship": "Update shipping and returns: same-day dispatch cutoff to 2 pm, and frozen returns to within 14 days of delivery.",
}
NAME = {"price": "pricing", "allergy": "allergen", "ship": "shipping"}
SECTION_NAME = {"price": "1. Price list", "allergy": "2. Allergen labels", "ship": "3. Shipping and returns"}
FILES_B = {"price": "product_sheet/1_prices.md", "allergy": "product_sheet/2_allergens.md", "ship": "product_sheet/3_shipping.md"}

TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Save the whole file with new content", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
]


def worker(role, cond, fs, lock, log):
    if cond == "B":
        sysmsg = "You are the %s agent. Your file is %s and only that one. You cannot write to any other file." % (NAME[role], FILES_B[role])
        user = TASK[role] + "\nFile: " + FILES_B[role]
    else:
        sysmsg = "You are the %s agent. You edit the shared document product_sheet.md." % NAME[role]
        user = TASK[role] + "\nFile: product_sheet.md"
        if cond == "C":
            user += "\nYour section is '%s' only. Do not change the other sections." % SECTION_NAME[role]
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]
    for _ in range(8):
        for k in range(5):
            try:
                r = client.chat.completions.create(model=MODEL, messages=msgs, tools=TOOLS, temperature=0.7)
                break
            except Exception:
                time.sleep(3 + 3 * k)
        m = r.choices[0].message
        msgs.append(m.model_dump(exclude_none=True))
        if not m.tool_calls:
            break
        for tc in m.tool_calls:
            a = json.loads(tc.function.arguments or "{}")
            p = (a.get("path") or "").strip().lstrip("./")
            with lock:   # one tool call is atomic - but 'read -> think for a while -> save the whole file' can still be interleaved
                if tc.function.name == "read_file":
                    out = {"content": fs[p]} if p in fs else {"error": "no such file"}
                    log.append((time.time(), role, "read", p))
                else:
                    if cond == "B" and p != FILES_B[role]:
                        out = {"error": "refused: not your file (you can write only %s)" % FILES_B[role]}
                        log.append((time.time(), role, "denied", p))
                    else:
                        fs[p] = a.get("content", "")
                        out = {"ok": True}
                        log.append((time.time(), role, "write", p))
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out, ensure_ascii=False)})


def run(cond, i):
    lock, log = threading.Lock(), []
    if cond == "B":
        fs = {FILES_B[k]: SEC[k] + "\n" for k in SEC}
    else:
        fs = {"product_sheet.md": DOC}
    t0 = time.time()
    if cond == "S":
        for role in ("price", "allergy", "ship"):
            worker(role, cond, fs, lock, log)
    else:
        th = [threading.Thread(target=worker, args=(role, cond, fs, lock, log)) for role in ("price", "allergy", "ship")]
        for t in th:
            t.start()
        for t in th:
            t.join()
    sec = time.time() - t0
    final = (HEAD + "\n\n" + "\n".join(fs[FILES_B[k]].strip() + "\n" for k in ("price", "allergy", "ship"))) if cond == "B" else fs["product_sheet.md"]
    g = grade(final)
    writes = [(r, p) for _, r, op, p in log if op == "write"]
    return dict(cond=cond, i=i, final=final, sec=round(sec, 1), log=[(round(t - t0, 1), r, op, p) for t, r, op, p in log],
                n_writes=len(writes), denied=sum(1 for _, _, op, _ in log if op == "denied"), **g)


CHECKS = [
    ("price: pizza sauce 79.30", r"Pizza Sauce 1 gal[^\n]*79\.30"),
    ("price: bbq 47.50", r"BBQ Sauce 18 oz[^\n]*47\.50"),
    ("allergy: gift box walnuts", r"Snack Gift Box[^\n]*walnut"),
    ("allergy: gift box almonds", r"Snack Gift Box[^\n]*almond"),
    ("allergy: buns sesame", r"Sesame Burger Buns[^\n]*:[^\n]*sesame"),
    ("ship: cutoff 2 pm", r"cutoff[^\n]*(2 ?pm|2:00|14:00)"),
    ("ship: returns 14 days", r"returns?[^\n]*14 days"),
]
KEEP = [r"Ranch Dressing 16 oz[^\n]*39\.80", r"Pizza Sauce 1 gal: [^\n]*soy", r"Free shipping on orders over \$50"]


def grade(final):
    got = [name for name, pat in CHECKS if re.search(pat, final, re.I)]
    kept = sum(1 for pat in KEEP if re.search(pat, final, re.I))
    return dict(survived=got, n_survived=len(got), kept=kept, ok=len(got) == len(CHECKS) and kept == len(KEEP))


def summary(rs):
    for c in ["A", "C", "B", "S"]:
        x = [r for r in rs if r["cond"] == c]
        if not x:
            continue
        print(c, "perfect %d/%d" % (sum(r["ok"] for r in x), len(x)), "| edits survived avg %.1f/7" % (sum(r["n_survived"] for r in x) / len(x)),
              "| keep-as-is kept %.1f/3" % (sum(r["kept"] for r in x) / len(x)), "| writes refused %d" % sum(r["denied"] for r in x),
              "| time %.1f s" % (sum(r["sec"] for r in x) / len(x)))


if __name__ == "__main__":
    conds = sys.argv[1:] or ["A", "C", "B", "S"]
    jobs = [(c, i) for c in conds for i in range(TRIALS)]
    with ThreadPoolExecutor(4) as ex:      # 4 runs at a time; inside a run, the 3 agents each get a thread
        res = list(ex.map(lambda a: run(*a), jobs))
    out = os.path.join(HERE, "results.json")
    old = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    old = [r for r in old if r["cond"] not in conds] + res
    json.dump(old, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summary(old)
