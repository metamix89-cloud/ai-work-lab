# -*- coding: utf-8 -*-
"""raw/cs 주간 파일의 표를 코드로 세어 '진짜' 주차 × 유형 건수와 변질 상위 상품을 보여 준다 — 위키가 센 숫자와 대조하는 기준.
사용: python _scratch/wiki/cs_counts.py [--wiki=wiki_ep2r]   (--wiki 를 주면 그 위키의 지표/고객-문의-집계 표와 변질 열을 비교)"""
import glob, os, re, sys
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
wk_cat, spoil_prod = {}, Counter()
for p in sorted(glob.glob(os.path.join(HERE, "raw", "cs", "2026-W*.md"))):
    wk = os.path.basename(p)[:8]
    c = Counter()
    for line in open(p, encoding="utf-8"):
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) >= 9 and cells[0].startswith("CS-"):
            c[cells[6]] += 1
            if cells[6] == "변질":
                spoil_prod[cells[5]] += 1
    wk_cat[wk] = c
cats = ["배송 지연", "포장 파손", "변질", "단순 변심", "오배송", "주문 조회", "결제 문의", "상품 문의", "알레르기 문의", "칭찬"]
print("%-9s " % "주차" + " ".join("%5s" % c[:4] for c in cats))
for wk, c in wk_cat.items():
    print("%-9s " % wk + " ".join("%5d" % c[k] for k in cats))
print("변질 상위 상품(전체 12주):", spoil_prod.most_common(4))
w = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--wiki=")), None)
if w:
    p = os.path.join(HERE, w, "pages", "지표-고객-문의-집계.md")
    if os.path.exists(p):
        t = open(p, encoding="utf-8").read()
        hdr = None
        print("\n위키 집계 표 vs 코드 (변질 열):")
        for line in t.splitlines():
            cells = [x.strip() for x in line.strip().strip("|").split("|")]
            if cells and cells[0] == "주차":
                hdr = cells
            elif hdr and cells and cells[0].startswith("2026-W") and "변질" in hdr:
                wk = cells[0][:8]
                wv = cells[hdr.index("변질")]
                cv = wk_cat.get(wk, Counter())["변질"]
                print("  %s 위키 %s · 코드 %d %s" % (wk, wv, cv, "" if str(cv) == wv else "← 다름"))
    else:
        print("집계 페이지 없음:", p)
