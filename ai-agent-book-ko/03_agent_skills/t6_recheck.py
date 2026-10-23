# -*- coding: utf-8 -*-
"""T6(재고 알림) 재채점 확인 — 처음 채점기는 품목 이름이 나온 '첫 줄'만 봤다.
계산 과정을 먼저 쓰고 알림 줄(🔴/🟢)을 뒤에 쓴 답은 맞아도 틀린 것으로 셌을 수 있다(영어판 ep038 에서 발견, 2026-10-22).
여기서는 '표시(🔴🟢⚪)가 있는 줄'로 다시 채점해 차이를 본다. results.json 은 고치지 않는다.
사용: python t6_recheck.py [results.json]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
fn = sys.argv[1] if len(sys.argv) > 1 else "results.json"
with open(os.path.join(HERE, fn), encoding="utf-8") as f:
    res = json.load(f)


def alert(t, k):
    return next((l for l in t.splitlines() if k in l and any(e in l for e in "🔴🟢⚪")), "")


for r in res:
    if r.get("task") != "T6" or "error" in r:
        continue
    t = r["answer"]
    ok2 = "🔴" in alert(t, "냉동만두") and "🟢" in alert(t, "떡볶이") and "🔴" in alert(t, "참기름")
    mark = "" if ok2 == r["ok"] else "  ← 다름"
    print("%s#%d 처음 %s · 다시 %s%s" % (r["cond"], r["seed"], r["ok"], ok2, mark))
    if mark:
        print("    " + t.replace("\n", " / ")[:300])
