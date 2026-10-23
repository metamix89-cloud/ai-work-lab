# -*- coding: utf-8 -*-
"""Print every run for one condition and case: grade, actions, final reply.
Usage: python show.py B 1      (case numbers start at 1)"""
import json, os, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "results.json"), encoding="utf-8") as f:
    res = json.load(f)
cond, case = sys.argv[1], int(sys.argv[2]) - 1
for r in res:
    if r["cond"] == cond and r["case"] == case:
        acts = " ".join("%s(%s)" % (l["tool"], l["args"].get("amount", "")) for l in r["log"])
        print("rep%d %s %s | %s\n   %s\n" % (r["rep"], "OK" if r["ok"] else "XX", r["why"], acts, r["final"]))
