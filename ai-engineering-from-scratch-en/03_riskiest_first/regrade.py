# -*- coding: utf-8 -*-
"""Re-grade saved plans with the current grader (no API calls). Usage: python regrade.py"""
import json, os, lab
HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "results.json")
rs = json.load(open(p, encoding="utf-8"))
for r in rs:
    r.update(lab.grade(r["report"]))
json.dump(rs, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
lab.summary(rs)
