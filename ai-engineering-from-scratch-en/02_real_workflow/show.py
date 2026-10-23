# -*- coding: utf-8 -*-
"""Print saved reports for reading by hand.
Usage: python show.py C [0 1 ...] [auto|five|hidden=<n>]   auto = only runs graded auto-approve, printing the matching window; five = only '5 min as fact' runs with the line"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
flt = [x for x in sys.argv[2:] if not x.isdigit()]
idx = [int(x) for x in sys.argv[2:] if x.isdigit()]
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    if "auto" in flt and not r["auto"]:
        continue
    if "five" in flt and not r["took5"]:
        continue
    print("=" * 30, cond, r["i"], "| hidden", r["n_hidden"], r["hidden"], "| 5min", r["took5"], "| auto", r["auto"], "| evid", r["evid"], "| words", r["words"])
    if "auto" in flt:
        for c in lab.chunks(r["report"]):
            if ("$50" in c or "50 dollar" in c or "fifty" in c) and lab.AUTO.search(c) and not lab.HUMAN.search(c):
                print("   >>", c[:500])
        continue
    if "five" in flt:
        for line in r["report"].splitlines():
            if lab.FIVE.search(line) and not lab.FIVE_NEG.search(line):
                print("   >>", line.strip()[:300])
        continue
    print(r["report"][:7000])
