# -*- coding: utf-8 -*-
"""'결제 익월 15일' 채점 재확인 — 처음 채점은 확인서 어디에든 '15일'이 있으면 맞다고 셌다.
영어판(04_context_compress)에서 지어낸 날짜 'November 15' 를 결제일로 잘못 센 일이 있어(2026-10-22), 한국어 결과도 확인한다.
'15일'이 들어간 줄이 결제 줄(결제 · 익월 · 대금 · 현금)인지 본다. results.json 은 고치지 않는다.
사용: python pay15_recheck.py [results.json]"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "results.json"), encoding="utf-8") as f:
    res = json.load(f)
diff = 0
for r in res:
    if "error" in r or "결제 익월 15일" not in r.get("kept", []):
        continue
    lines = [l.strip() for l in r["final"].splitlines() if "15일" in l]
    ok = any(re.search(r"결제|익월|대금|현금", l) for l in lines)
    if not ok:
        diff += 1
        print("%s#%d  결제 줄 아님: %s" % (r["strategy"], r["seed"], " / ".join(lines)[:200]))
print("다른 판정 %d건" % diff)
