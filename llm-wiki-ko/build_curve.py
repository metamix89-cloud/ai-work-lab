# -*- coding: utf-8 -*-
"""results/build_full.json 에서 원본을 넣을 때마다 페이지 수가 어떻게 늘었는지 묶음(폴더)별로 보여 준다 — 원고의 '위키가 자라는' 숫자용.
사용: python _scratch/wiki/build_curve.py"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "results", "build_full.json"), encoding="utf-8"))
prev_group, prev_pages, tok = None, 0, 0
rows = []
for i, r in enumerate(d["log"], 1):
    g = r["source"].split("/")[0]
    tok += r["tokens"]
    if g != prev_group and prev_group is not None:
        rows.append((prev_group, n_src, prev_pages, tok_g))
        tok_g = 0
    if g != prev_group:
        n_src, tok_g = 0, 0
    n_src += 1; tok_g += r["tokens"]
    prev_group, prev_pages = g, r["stats"]["pages"]
rows.append((prev_group, n_src, prev_pages, tok_g))
print("%-10s %6s %10s %12s" % ("묶음", "원본", "누적 페이지", "토큰"))
for g, n, p, t in rows:
    print("%-10s %6d %10d %12s" % (g, n, p, format(t, ",")))
big = sorted(d["log"], key=lambda r: -len(r["pages_written"]))[:3]
print("한 번에 가장 많이 건드린 원본:", "; ".join("%s → %d페이지" % (r["source"], len(r["pages_written"])) for r in big))
