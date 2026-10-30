# -*- coding: utf-8 -*-
"""ep088 새 실측 비용 합계 + PRD 글자 수. 사용: python _scratch/s2s/tools/ep088_cost.py"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
LAB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "02_s2s_meeting_room")
prd_cost = 0.0
for p in sorted(glob.glob(os.path.join(LAB, "ai_prd", "*.json"))):
    j = json.load(open(p, encoding="utf-8"))
    prd_cost += j.get("total_cost_usd") or 0
    print(os.path.basename(p), "$%.2f" % (j.get("total_cost_usd") or 0), j.get("prd_chars"), "자")
build_cost, secs = 0.0, []
for p in sorted(glob.glob(os.path.join(LAB, "runs", "P[12]_*", "build.json"))):
    j = json.load(open(p, encoding="utf-8"))
    build_cost += j.get("total_cost_usd") or 0
    secs.append(j.get("wall_s") or 0)
print("PRD 쓰기 합 $%.2f · 빌드 합 $%.2f · 전체 $%.2f" % (prd_cost, build_cost, prd_cost + build_cost))
print("빌드 시간 %.0f~%.0f초" % (min(secs), max(secs)))
print("사람 PRD", len(open(os.path.join(LAB, "PRD.md"), encoding="utf-8").read()), "자")
