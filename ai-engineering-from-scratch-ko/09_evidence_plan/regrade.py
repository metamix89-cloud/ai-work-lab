# -*- coding: utf-8 -*-
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
p = os.path.join(HERE, "results.json")
rs = json.load(open(p, encoding="utf-8"))
for r in rs:
    r.update(lab.grade(r["report"]))
json.dump(rs, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
lab.summary(rs)
