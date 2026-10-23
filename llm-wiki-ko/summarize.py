# -*- coding: utf-8 -*-
"""results/epN.json 을 조건 × 그룹 표로 요약하고 틀린 답을 보여 준다(채점기 오탐 확인용).
사용: python _scratch/wiki/summarize.py ep1 [--wrong] [--cond=full] [--max=30]"""
import json, os, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
name = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "ep1"
args = sys.argv[1:]
only = next((a.split("=", 1)[1] for a in args if a.startswith("--cond=")), None)
mx = int(next((a.split("=", 1)[1] for a in args if a.startswith("--max=")), 30))
res = json.load(open(os.path.join(HERE, "results", name + ".json"), encoding="utf-8"))
res = [r for r in res if "ok" in r and (only is None or r["cond"] == only)]
groups = sorted({r["group"] for r in res})
print("%-6s %s  %6s %7s %8s" % ("조건", " ".join("%7s" % g for g in groups), "정답", "근거", "토큰/문항"))
for c in sorted({r["cond"] for r in res}):
    rs = [r for r in res if r["cond"] == c]
    cells = []
    for g in groups:
        gs = [r for r in rs if r["group"] == g]
        cells.append("%3d/%-3d" % (sum(r["ok"] for r in gs), len(gs)))
    print("%-6s %s  %3d/%-3d %3d/%-3d %8.0f" % (c, " ".join(cells), sum(r["ok"] for r in rs), len(rs), sum(1 for r in rs if r["grounded"]), len(rs), sum(r["tokens"] for r in rs) / len(rs)))
bf = os.path.join(HERE, "results", "build_full.json")
if os.path.exists(bf):
    d = json.load(open(bf, encoding="utf-8"))
    tok = sum(r["tokens"] for r in d["log"])
    print("위키 빌드: 원본 %d개 · %d분 · 토큰 %s(원본당 %s) · 페이지 %d · 원본당 수정 %.1f페이지" % (len(d["log"]), d["sec"] // 60, format(tok, ","), format(tok // len(d["log"]), ","), d["stats"]["pages"], sum(len(r["pages_written"]) for r in d["log"]) / len(d["log"])))
errs = [r for r in json.load(open(os.path.join(HERE, "results", name + ".json"), encoding="utf-8")) if "error" in r]
if errs:
    print("오류 %d건:" % len(errs), errs[0].get("error"))
if "--wrong" in args:
    print("\n── 틀린 답")
    for r in [r for r in res if not r["ok"]][:mx]:
        print("[%s %s t%d] %s\n   %s\n" % (r["cond"], r["id"], r["trial"], r["why"], r["answer"].replace("\n", " / ")[:300]))
