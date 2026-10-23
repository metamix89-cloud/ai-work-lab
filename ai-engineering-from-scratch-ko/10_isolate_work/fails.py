# -*- coding: utf-8 -*-
"""완벽하지 않은 실행만: python fails.py <조건>"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1] if len(sys.argv) > 1 else "S"
for r in [x for x in rs if x["cond"] == cond and not x["ok"]]:
    lost_keep = [p for p in lab.KEEP if not re.search(p, r["final"])]
    print("%s%d 살아남은 %d 잃은 '그대로 둘 것' %s" % (cond, r["i"], r["n_survived"], lost_keep))
    print("   ", r["final"].replace("\n", " / ")[:700])
