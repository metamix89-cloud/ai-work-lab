# -*- coding: utf-8 -*-
"""조건별 실패 이유 세기: python fails.py <조건>"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1] if len(sys.argv) > 1 else "B"
for r in [x for x in rs if x["cond"] == cond]:
    new = [l for l in r["target_after"].splitlines() if "2026-11-01" in l]
    why = []
    if not r["writes"]:
        why.append("안 고침")
    if new and not r["new_row"]:
        why.append("새 행 값: " + new[0])
    if not r["old_row"]:
        why.append("옛 행 사라짐(덮어씀)")
    print("%s%d %s | 읽은 파일 %s | %s" % (cond, r["i"], "정확" if r["ok"] else "실패", [p.split("/")[-1] for p in r["reads"]], " · ".join(why)))
