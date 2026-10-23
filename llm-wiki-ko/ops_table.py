# -*- coding: utf-8 -*-
"""10편 결과 표: results/ep10*.json 의 조건별 주차 추이(최신 · 낡음 · 없음 · 지난 예정 · 페이지)와 최종 항목 상태, 지난 예정 줄.
사용: python _scratch/wiki/ops_table.py ep10 [--lines]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
name = next((a for a in args if not a.startswith("--")), "ep10")
d = json.load(open(os.path.join(HERE, "results", name + ".json"), encoding="utf-8"))
for cond, r in d.items():
    print("== %s (토큰 %s · %ds)" % (cond, format(r["tokens"], ","), r["sec"]))
    print("   %-5s %5s %5s %5s %7s %6s  %s" % ("주차", "최신", "낡음", "없음", "지난예정", "페이지", "루틴(고친 페이지 · 전→후)"))
    for wk in r["weeks"]:
        g = wk["grade"]; ro = wk.get("routine")
        print("   %-5s %5d %5d %5d %7d %6d  %s" % (wk["week"], g["fresh"], g["stale"], g["missing"], g["overdue"], g["pages"], ("%d · %d→%d" % (ro[0], ro[2], ro[3])) if ro else "-"))
    f = r["final"]
    print("   최종  %5d %5d %5d %7d %6d  %s" % (f["fresh"], f["stale"], f["missing"], f["overdue"], f["pages"], "  ".join("%s:%s" % (p["id"], p["state"]) for p in f["items"])))
    if "--lines" in args:
        for s, l in f["overdue_lines"]:
            print("     [지난 예정] %s: %s" % (s, l[:110]))
