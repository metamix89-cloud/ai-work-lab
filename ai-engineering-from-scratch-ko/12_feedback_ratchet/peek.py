# -*- coding: utf-8 -*-
"""신호별 줄 보기: python peek.py <조건> <신호 번호> [몇 개]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond, sig = sys.argv[1], int(sys.argv[2])
n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
for r in [x for x in rs if x["cond"] == cond][:n]:
    rows = [row for row in lab.parse(r["report"]) if sig in row["nums"]]
    print("%s%d | %s" % (cond, r["i"], " // ".join(" | ".join(row["cells"])[:200] for row in rows) or "(줄 없음)"))
