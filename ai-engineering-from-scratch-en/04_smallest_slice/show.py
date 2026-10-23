# -*- coding: utf-8 -*-
"""Read es04 results by hand.
Usage: python show.py <cond> [i ...]        full answers
       python show.py P scope              the scope part the grader looked at, with its frozen / auto / stop verdicts"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
mode = next((a for a in sys.argv[2:] if not a.isdigit()), "")
idx = [int(a) for a in sys.argv[2:] if a.isdigit()]
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    if cond in "ABC":
        print("==", cond, r["i"], "| pick", r["pick"], "|", r["report"][:400].replace("\n", " / "))
        continue
    print("=" * 20, cond, r["i"], "| frozen", r["frozen"], "| real", r["real"], "| staff", r["staff"], "| auto", r["auto"], "| stop", r["stop"])
    if mode == "scope":
        print(lab.scope_part(r["report"]).strip()[:900])
    else:
        print(r["report"][:5000])
