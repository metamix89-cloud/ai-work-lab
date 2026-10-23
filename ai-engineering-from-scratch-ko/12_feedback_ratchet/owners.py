# -*- coding: utf-8 -*-
"""담당 칸 분석: 한 사람(이름 · 직함)인가, 여러 팀인가."""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
for c, col in (("A", 2), ("B", 4)):
    tot = one = multi = 0
    for r in [x for x in rs if x["cond"] == c]:
        for row in lab.parse(r["report"]):
            if len(row["cells"]) <= col:
                continue
            o = row["cells"][col]
            tot += 1
            if re.search(r"[,/·]|및|와 |과 ", o):
                multi += 1
            elif re.search(r"[가-힣]{2,3}(\s|$)|과장|대리|팀장|주임|매니저", o) and not o.endswith("팀"):
                one += 1
    print(c, "줄 %d · 여러 팀 공동 %d (%.0f%%) · 한 사람 %d (%.0f%%)" % (tot, multi, 100 * multi / tot, one, 100 * one / tot))
