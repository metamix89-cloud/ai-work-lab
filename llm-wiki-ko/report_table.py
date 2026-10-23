# -*- coding: utf-8 -*-
"""8편 보고서 결과 표: results/ep8*.json 의 조건별 요소 평균 · 항목별 찾은 횟수 · 지어낸 숫자 · 심은 틀린 값 · 토큰, --sample 로 보고서 원문 하나.
사용: python _scratch/wiki/report_table.py ep8 [ep8b ...] [--sample=wiki] [--trial=0]"""
import json, os, sys
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
names = [a for a in args if not a.startswith("--")]
opt = lambda k, d=None: next((a.split("=", 1)[1] for a in args if a.startswith("--%s=" % k)), d)
items = [it["id"] + " " + it["name"][:14] for it in json.load(open(os.path.join(HERE, "report_items.json"), encoding="utf-8"))["items"]]
for n in names:
    res = [r for r in json.load(open(os.path.join(HERE, "results", n + ".json"), encoding="utf-8")) if "grade" in r]
    print("== %s" % n)
    print("%-6s %4s %7s %7s %9s %9s %9s  %s" % ("조건", "회", "요소/5", "근거/5", "지어낸수", "틀린값", "토큰", "  ".join(i.split()[0] for i in items)))
    for c in ("wiki", "rag", "dump"):
        rs = [r for r in res if r["cond"] == c]
        if not rs:
            continue
        k = len(rs)
        per = Counter(p["id"] for r in rs for p in r["grade"]["items"] if p["found"])
        mu = Counter(x for r in rs for x in r["grade"]["made_up"]); pw = Counter(x for r in rs for x in r["grade"]["planted_wrong"])
        print("%-6s %4d %7.1f %7.1f %9d %9d %9.0f  %s" % (c, k, sum(r["grade"]["found"] for r in rs) / k, sum(r["grade"]["grounded"] for r in rs) / k,
                                                       sum(mu.values()), sum(pw.values()), sum(r["tokens"] for r in rs) / k,
                                                       "  ".join("%s:%d" % (i.split()[0], per[i.split()[0]]) for i in items)))
        if mu or pw:
            print("       지어낸 수: %s · 틀린 값: %s" % (dict(mu), dict(pw)))
    if opt("sample"):
        t = int(opt("trial", 0))
        r = next(r for r in res if r["cond"] == opt("sample") and r["trial"] == t)
        print("\n── %s t%d 보고서 (요소 %d · 지어낸 %s · 틀린 값 %s)\n%s" % (opt("sample"), t, r["grade"]["found"], r["grade"]["made_up"], r["grade"]["planted_wrong"], r["report"][:1800]))
