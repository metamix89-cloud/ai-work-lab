# -*- coding: utf-8 -*-
"""12편 비용표: 편별 위키 빌드 토큰 · 페이지 · 시간, 묻기 토큰/문항, 실험 결과 파일의 토큰 합. 돈은 gpt-4.1-mini 공개 단가로 어림(입력 $0.40/M · 출력 $1.60/M, 우리 토큰 수는 입력+출력 합이라 전부 입력 단가로 계산한 하한과 1:4 가정의 어림 둘 다).
사용: python _scratch/wiki/cost_table.py"""
import glob, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
usd = lambda tok: (tok / 1e6 * 0.40, tok / 1e6 * (0.8 * 0.40 + 0.2 * 1.60))      # (하한, 어림)
print("== 위키 빌드 (편 · 원본 묶음 · 페이지 · 토큰 · 분 · $하한~어림)")
rows = [("1편 전체(규칙 없음)", "build_full"), ("2편 v4 cs", "build_ep2d"), ("3편 +거래처", "build_ep3"), ("4편 +회의록", "build_ep4r"), ("5편 +규정(조항)", "build_ep5c"), ("7편 +매출", "build_ep7"),
        ("11편 전체 재빌드(규칙)", "build_ep11p"), ("11편 전체(규칙 없음)", "build_ep11n"), ("11편 전체(코드 가림)", "build_ep11m")]
chain = 0
for name, f in rows:
    p = os.path.join(R, f + ".json")
    if not os.path.exists(p):
        print("   %-22s (없음)" % name); continue
    d = json.load(open(p, encoding="utf-8")); tok = sum(r["tokens"] for r in d["log"])
    if f in ("build_ep2d", "build_ep3", "build_ep4r", "build_ep5c", "build_ep7"):
        chain += tok
    lo, hi = usd(tok)
    print("   %-22s 원본 %3d · 페이지 %3d · 토큰 %9s · %3d분 · $%.2f~%.2f" % (name, len(d["log"]), d["stats"]["pages"], format(tok, ","), d.get("sec", 0) // 60, lo, hi))
lo, hi = usd(chain)
print("   %-22s 토큰 %9s · $%.2f~%.2f" % ("규칙 위키 누적(2~7편)", format(chain, ","), lo, hi))
print("\n== 묻기 (결과 파일 · 조건 · 문항 수 · 토큰/문항 · 전체 토큰 · $)")
for f in ["ep1", "ep7"]:
    res = [r for r in json.load(open(os.path.join(R, f + ".json"), encoding="utf-8")) if "tokens" in r]
    for c in sorted({r["cond"] for r in res}):
        rs = [r for r in res if r["cond"] == c]; tok = sum(r["tokens"] for r in rs)
        print("   %-5s %-6s %4d문항 · %6.0f/문항 · %9s · $%.2f~%.2f" % (f, c, len(rs), tok / len(rs), format(tok, ","), *usd(tok)))
print("\n== 편별 실험 토큰 합 (results/*.json 의 tokens 필드)")
tot = 0
for p in sorted(glob.glob(os.path.join(R, "*.json"))):
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    def walk(x):
        if isinstance(x, dict):
            return (x.get("tokens", 0) if isinstance(x.get("tokens"), (int, float)) else 0) + sum(walk(v) for k, v in x.items() if k != "tokens")
        if isinstance(x, list):
            return sum(walk(v) for v in x)
        return 0
    t = walk(d); tot += t
    if t:
        print("   %-24s %10s" % (os.path.basename(p), format(int(t), ",")))
lo, hi = usd(tot)
print("   %-24s %10s  ≈ $%.1f~%.1f" % ("합계", format(int(tot), ","), lo, hi))
