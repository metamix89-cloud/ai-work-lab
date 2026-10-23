# -*- coding: utf-8 -*-
"""결과 보기: python peek.py <조건> [과제번호]"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1] if len(sys.argv) > 1 else "B"
x = [r for r in rs if r["cond"] == cond]
if len(sys.argv) > 2:
    x = [r for r in x if r["task"] == int(sys.argv[2])]
print(cond, "부가세 말 있음 %d · '별도' %d · 유효기간 말 있음 %d" % (sum(1 for r in x if "부가세" in r["report"]), sum(1 for r in x if "별도" in r["report"]),
                                                      sum(1 for r in x if "유효" in r["report"])))
for r in x[:2]:
    print("== 과제 %d 실패 %s" % (r["task"], r["fails"]))
    print(r["report"][:900])
