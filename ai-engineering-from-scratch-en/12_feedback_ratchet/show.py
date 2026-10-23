# -*- coding: utf-8 -*-
"""Read es12 plan tables by hand. Usage: python show.py <cond> [i ...] [signal=<n>]  - prints each table row (signals · owner · the rest); signal=8 prints only rows containing that signal"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1]
idx = [int(a) for a in sys.argv[2:] if a.isdigit()]
sig = next((int(a.split("=")[1]) for a in sys.argv[2:] if a.startswith("signal=")), None)
col = 2 if cond == "A" else 4
for r in rs:
    if r["cond"] != cond or (idx and r["i"] not in idx):
        continue
    print("=" * 12, cond, r["i"], "| rows", r["n_rows"], "| dup", r["dup_phone"], "| fix1 struct", r["fix1_struct"], "| fix5 rt", r["fix5_runtime"], "| retire8", r["retire8"])
    for row in lab.parse(r["report"]):
        if sig and sig not in row["nums"]:
            continue
        owner = row["cells"][col] if len(row["cells"]) > col else "?"
        rest = " | ".join(c for k, c in enumerate(row["cells"]) if k not in (0, col))
        print("   %-12s owner=%-28s %s" % (",".join(str(n) for n in sorted(row["nums"])), owner[:28], rest[:150]))
