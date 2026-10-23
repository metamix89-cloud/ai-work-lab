# -*- coding: utf-8 -*-
"""Re-grade saved reports with the current grader (no API calls). Usage: python regrade.py [results.json]"""
import json, sys, lab
f = sys.argv[1] if len(sys.argv) > 1 else "results.json"
rs = json.load(open(f, encoding="utf-8"))
for r in rs:
    r.update(lab.grade(r["report"]))
json.dump(rs, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
lab.summary(rs)
