# -*- coding: utf-8 -*-
"""실행 기록 보기: python peek.py <조건> [번호]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1] if len(sys.argv) > 1 else "A"
x = [r for r in rs if r["cond"] == cond]
if len(sys.argv) > 2:
    x = [r for r in x if r["i"] == int(sys.argv[2])]
for r in x[:3]:
    print("== %s%d 살아남은 %s 유지 %d" % (cond, r["i"], r["survived"], r["kept"]))
    for t, role, op, p in r["log"]:
        print("   %5.1f초 %-8s %-6s %s" % (t, role, op, p))
    print("   최종:", r["final"].replace("\n", " / ")[:600])
