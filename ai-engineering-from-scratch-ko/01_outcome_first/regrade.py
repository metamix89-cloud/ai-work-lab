# -*- coding: utf-8 -*-
"""저장된 보고서를 지금 채점기로 다시 채점 (API 호출 없음)."""
import json, sys, lab
f = sys.argv[1] if len(sys.argv) > 1 else "results.json"
rs = json.load(open(f, encoding="utf-8"))
for r in rs:
    r.update(lab.grade(r["report"]))
json.dump(rs, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for c in sorted({r["cond"] for r in rs}):
    x = [r for r in rs if r["cond"] == c]
    print(c, "완벽", sum(1 for r in x if not r["missed"] and not r["false"] and not r["price"]), "/", len(x),
          "| 찾음 %.1f/6" % (sum(len(r["found"]) for r in x) / len(x)), "| 놓침 있음", sum(1 for r in x if r["missed"]),
          "| 잘못표시 합", sum(len(r["false"]) for r in x), "| 단가노출", sum(1 for r in x if r["price"]),
          "| 비목표", sum(1 for r in x if r["nongoal"]), "| 글자 %d" % (sum(r["chars"] for r in x) / len(x)),
          "| 검산 %.1f/6" % (sum(r["evidence"] for r in x) / len(x)), "| 토큰 %d" % (sum(r["tokens"] for r in x) / len(x)))
