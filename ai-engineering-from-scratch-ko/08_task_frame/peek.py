# -*- coding: utf-8 -*-
"""결과 들여다보기: python peek.py <조건> [몇 개]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1] if len(sys.argv) > 1 else "A"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
for r in [x for x in rs if x["cond"] == cond][:n]:
    print("== %s%d ok=%s 읽음=%s 씀=%s" % (cond, r["i"], r["ok"], r["reads"], r["writes"]))
    print("   단가표:", r["target_after"].replace("\n", " / ")[:300])
    print("   답:", r["final"][:500].replace("\n", " / "))
