# -*- coding: utf-8 -*-
"""「이 화면, PRD 로는 이렇게」 시즌 전체 숫자 — 편마다 A · B · C 점수, 시즌 합계, 비용.
사용: python _scratch/s2s/tools/season_summary.py [01_s2s_dashboard ...]   (기본: _scratch/s2s/lab_ep07* · lab_ep08*)"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
labs = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "lab_ep07[1-9]")) + glob.glob(os.path.join(ROOT, "lab_ep08[0-9]")))
tot = {c: [0, 0] for c in "ABC"}
cost = {c: 0.0 for c in "ABC"}
nine = {c: 0 for c in "ABC"}
print("| 편 | A | B | C |")
print("|---|---|---|---|")
for lab in labs:
    p = os.path.join(lab, "results.json")
    if not os.path.exists(p):
        continue
    r = json.load(open(p, encoding="utf-8"))
    row = []
    for c in "ABC":
        sc = [r[k]["passed"] for k in sorted(r) if k.startswith(c) and k[1:].isdigit()]
        tot[c][0] += sum(sc)
        tot[c][1] += 9 * len(sc)
        nine[c] += sum(1 for s in sc if s == 9)
        cost[c] += sum((r[k].get("build") or {}).get("total_cost_usd") or 0 for k in r if k.startswith(c) and k[1:].isdigit())
        row.append(" · ".join(str(s) for s in sc))
    print("| %s | %s |" % (os.path.basename(lab).replace("lab_", ""), " | ".join(row)))
for c in "ABC":
    print("%s: 통과 %d / %d (%.1f%%) · 9/9 인 실행 %d · 비용 $%.2f" % (c, tot[c][0], tot[c][1], 100 * tot[c][0] / max(1, tot[c][1]), nine[c], cost[c]))
