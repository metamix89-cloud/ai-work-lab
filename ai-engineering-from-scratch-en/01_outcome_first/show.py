# -*- coding: utf-8 -*-
"""Print saved reports for reading by hand. Usage: python show.py F [0 1 ...]   (no index = all runs of that condition, grade line first)"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
flt = [x for x in sys.argv[2:] if not x.isdigit()]        # perfect | leak | missed
idx = [int(x) for x in sys.argv[2:] if x.isdigit()]
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    if "perfect" in flt and (r["missed"] or r["false"] or r["price"]):
        continue
    if "leak" in flt and not r["price"]:
        continue
    print("=" * 30, cond, r["i"], "| found", r["found"], "| missed", r["missed"], "| false", r["false"], "| cost", r["price"], "| non-goals", r["nongoal"],
          "| verifiable", r["evidence"], "| words", r["words"])
    if r.get("qa") and r["qa"].get("q"):
        print("--- Q:", r["qa"]["q"][:1500], "\n--- A:", r["qa"]["a"][:800])
    if r.get("qa") and r["qa"].get("errors"):
        print("--- errors:", len(r["qa"]["errors"]), "|", r["qa"]["errors"][0][-300:].strip())
    if "code" in flt:
        print(r["code"])
        continue
    print(r["report"][:6000])
