# -*- coding: utf-8 -*-
"""Print full answers (and tool calls) for one condition of results.json, for grading by hand.
Usage: python show.py A      (conditions: A, B, C, D0, D)"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, sys.argv[2] if len(sys.argv) > 2 else "results.json"), encoding="utf-8") as f:
    res = json.load(f)
for r in res:
    if r["cond"] == sys.argv[1]:
        print("--- %s%d (%d model calls)" % (r["cond"], r["k"], r["model_calls"]))
        for l in r["log"]:
            print("   ", l[:160])
        print("   A:", r["answer"].replace("\n", " "))
