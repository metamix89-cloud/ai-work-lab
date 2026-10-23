# -*- coding: utf-8 -*-
"""Read es08 runs by hand. Usage: python show.py <cond> [i ...]  - writes, the pizza-sauce rows after the run, wrong prices, and the final report"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
idx = [int(a) for a in sys.argv[2:]]
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    print("=" * 16, cond, r["i"], "| ok", r["ok"], "| new", r["new_row"], "| old", r["old_row"], "| wrong", r["wrong_price"], "| others", r["others"],
          "| contract", r["contract"], "| issued", r["issued"], "| readme", r["read_readme"], "| contract read", r["read_contract"])
    print("   reads:", r["reads"][:8], "| writes:", r["writes"])
    for l in r["target_after"].splitlines():
        if "pizza" in l.lower():
            print("   ROW:", l.strip())
    print("   FINAL:", r["final"][:500].replace("\n", " / "))
