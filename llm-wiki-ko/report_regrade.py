# -*- coding: utf-8 -*-
"""저장된 보고서 결과(results/ep8*.json)를 고친 채점기로 다시 채점한다(API 재호출 없음).
사용: python _scratch/wiki/report_regrade.py ep8 [ep8b ...]"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_grade import grade_report
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
for name in sys.argv[1:]:
    path = os.path.join(HERE, "results", name + ".json")
    res = json.load(open(path, encoding="utf-8"))
    ch = 0
    for r in res:
        if "report" not in r:
            continue
        g = grade_report(r["report"])
        ch += g != r["grade"]; r["grade"] = g
    json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%s: 바뀐 채점 %d건" % (name, ch))
