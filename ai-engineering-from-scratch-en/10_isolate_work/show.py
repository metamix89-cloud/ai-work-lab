# -*- coding: utf-8 -*-
"""Read es10 runs by hand. Usage: python show.py <cond> [i ...]   - the tool-call timeline (t, agent, op, path), survived edits, and the final document"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
idx = [int(a) for a in sys.argv[2:]]
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    print("=" * 16, cond, r["i"], "| ok", r["ok"], "| survived", r["n_survived"], r["survived"], "| kept", r["kept"], "| refused", r["denied"], "| %.1f s" % r["sec"])
    for t, role, op, p in r["log"]:
        print("   %5.1f s  %-8s %-6s %s" % (t, role, op, p))
    print(r["final"])
