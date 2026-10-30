# -*- coding: utf-8 -*-
"""ep089 원고 숫자 확인 — 조건별 지킴 · 비용 · 토큰 · 코드 줄 · 수칙.
사용: python _scratch/s2s/tools/ep089_summary.py"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
LAB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "11_s2s_order_stock")
R = json.load(open(os.path.join(LAB, "rules_results.json"), encoding="utf-8"))
total = 0.0
for c in "NSL":
    rows = [R["%s%d" % (c, i)] for i in (1, 2, 3)]
    cost = sum(r["cost"] for r in rows)
    total += cost
    print(c, "DoD", [r["passed"] for r in rows], "지킴", [r["kept"] for r in rows], "합", sum(r["kept"] for r in rows), "/33",
          "비용 합 $%.2f" % cost, "회당", ["%.2f" % r["cost"] for r in rows], "턴", [r["turns"] for r in rows], "시간", [r["wall_s"] for r in rows])
    print("  입력 토큰", [r["input_tokens"] for r in rows], "평균", sum(r["input_tokens"] for r in rows) // 3, "출력 토큰", [r["output_tokens"] for r in rows])
    lines = [r["sizes"]["py_lines"] + r["sizes"]["web_lines"] for r in rows]
    print("  코드 줄", lines, "평균 %.1f" % (sum(lines) / 3), "파일", [r["sizes"]["file_count"] for r in rows])
    for k in [k for k in rows[0]["filler"] if k.startswith("F")]:
        print("   ", k, sum(1 for r in rows if r["filler"][k]), "/ 3")
print("전체 비용 $%.2f" % total)
