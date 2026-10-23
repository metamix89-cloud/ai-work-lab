# -*- coding: utf-8 -*-
"""9편 재발 표: results/ep9*.json 의 조건별 — 메모마다 넣기 전 틀린 값이 있던 페이지 · 넣은 뒤 재발 페이지 · 토큰.
사용: python _scratch/wiki/fix_table.py ep9 ep9g [--detail]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
names = [a for a in args if not a.startswith("--")]
ids = ["E%d" % i for i in range(1, 11)]
print("%-9s %-10s %7s %7s %8s  %s" % ("결과", "조건", "이미틀림", "재발", "토큰", "  ".join(ids)))
for n in names:
    d = json.load(open(os.path.join(HERE, "results", n + ".json"), encoding="utf-8"))
    for cond, r in d.items():
        cells = []
        for i in ids:
            b, a = r["before"].get(i, []), r["after"].get(i, [])
            cells.append("재발" if set(a) - set(b) else ("기존" if b else "ok"))
        print("%-9s %-10s %7d %7d %8d  %s" % (n, cond, sum(1 for v in r["before"].values() if v), len(r["recurred"]), r["tokens"], "  ".join("%-3s" % c for c in cells)))
        if "--detail" in args:
            for i in ids:
                b, a = r["before"].get(i, []), r["after"].get(i, [])
                if b or a:
                    print("     %-4s 전: %s  후: %s" % (i, ", ".join(b)[:70], ", ".join(a)[:90]))
