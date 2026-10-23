# -*- coding: utf-8 -*-
"""순서 표와 분류 보기: python peek.py <조건> [몇 개]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1] if len(sys.argv) > 1 else "A"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
for r in [x for x in rs if x["cond"] == cond][:n]:
    print("== %s%d 문자>법무 %s 문자>시스템 %s 홈>법무 %s" % (cond, r["i"], r["sms_after_legal"], r["sms_after_system"], r["web_after_legal"]))
    for k, (t, d) in sorted(lab.parse_table(r["report"]).items()):
        print("   %2d [%-6s] %-60s <- %s" % (k, lab.kind_of(t), t[:60], d))
