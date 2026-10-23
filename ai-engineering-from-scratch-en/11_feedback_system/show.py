# -*- coding: utf-8 -*-
"""Read es11 quotes by hand. Usage: python show.py <cond A|B|C|D> [fails] [task ...]  - prints the price lines, tax and validity lines, and the fails"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
only_fails = "fails" in sys.argv[2:]
tasks = [int(a) for a in sys.argv[2:] if a.isdigit()]
for r in sorted(rs, key=lambda r: (r["task"], r["trial"])):
    if r["cond"] != cond or (only_fails and r["ok"]) or (tasks and r["task"] not in tasks):
        continue
    day, cust, items = lab.TASKS[r["task"]]
    print("=" * 12, cond, "task", r["task"], "trial", r["trial"], "|", day, cust, "| fails", r["fails"], "| retried", r.get("retried"))
    for l in r["report"].splitlines():
        if re.search(r"pizza|bbq|ranch|tax|valid|total", l, re.I):
            print("   ", l.strip()[:140])
