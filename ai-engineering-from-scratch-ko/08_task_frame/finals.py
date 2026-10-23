# -*- coding: utf-8 -*-
"""고치지 않은 실행의 마지막 답 보기: python finals.py <조건>"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1] if len(sys.argv) > 1 else "D"
for r in [x for x in rs if x["cond"] == cond and not x["writes"]]:
    print("== %s%d" % (cond, r["i"]))
    print("  ", r["final"][-700:].replace("\n", " / "))
