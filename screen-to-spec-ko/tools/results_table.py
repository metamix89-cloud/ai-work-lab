# -*- coding: utf-8 -*-
"""results.json → 원고용 표. DoD 통과 · 떨어진 T · PRD 밖 라우트 · 시키지 않은 기능(코드 패턴) · 턴 · 비용.
사용: python _scratch/s2s/tools/results_table.py <lab_dir>"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
lab = os.path.abspath(sys.argv[1])
R = json.load(open(os.path.join(lab, "results.json"), encoding="utf-8"))

# PRD 8 범위 밖 목록을 코드 패턴으로 — 편마다 lab/grading.json 의 extra_patterns (사람이 다시 확인한다)
_g = os.path.join(lab, "grading.json")
EXTRA = list(json.load(open(_g, encoding="utf-8")).get("extra_patterns", {}).items()) if os.path.exists(_g) else []


def scan(run_dir):
    hits = {}
    for p in glob.glob(os.path.join(run_dir, "**", "*.*"), recursive=True):
        if not p.endswith((".py", ".html", ".js", ".css")) or "_grader" in p or os.sep + "tests" + os.sep in p:
            continue
        src = open(p, encoding="utf-8", errors="ignore").read()
        for name, pat in EXTRA:
            if re.search(pat, src, re.I):
                hits.setdefault(name, []).append(os.path.basename(p))
    return hits


rows = []
for name in sorted(R):
    r = R[name]
    b = r.get("build") or {}
    fails = [t for t, v in sorted(r["tests"].items(), key=lambda x: int(x[0][1:])) if v != "pass"]
    hits = scan(os.path.join(lab, "runs", name))
    rows.append((name, r["passed"], fails, r["extra_routes"], sorted(hits), b.get("num_turns"), b.get("total_cost_usd") or 0,
                 (b.get("usage") or {}).get("output_tokens"), r.get("tests_modified")))
print("| 실행 | DoD | 떨어진 것 | PRD 밖 라우트 | 코드에 보이는 범위 밖 패턴 | 턴 | 비용 | 출력 토큰 | 자기 테스트 |")
print("|---|---|---|---|---|---|---|---|---|")
for name, p, fails, routes, hits, turns, cost, out_tok, tm in rows:
    print("| %s | %d/9 | %s | %s | %s | %s | $%.2f | %s | %s |" % (name, p, " ".join(fails) or "—", " ".join(routes) or "—",
                                                                 ", ".join(hits) or "—", turns, cost, out_tok, tm))
print()
for cond in "ABC":
    sel = [x for x in rows if x[0].startswith(cond)]
    if sel:
        print("%s: DoD %s · 평균 %.1f/9 · 턴 %s · 비용 합 $%.2f" % (cond, "/".join(str(x[1]) for x in sel), sum(x[1] for x in sel) / len(sel),
                                                               "/".join(str(x[5]) for x in sel), sum(x[6] for x in sel)))
print()
for name in sorted(R):
    det = R[name].get("detail") or {}
    for t in sorted(det, key=lambda x: int(x[1:])):
        if R[name]["tests"].get(t) != "pass":
            print(name, t, det[t][:200].replace("\n", " "))
