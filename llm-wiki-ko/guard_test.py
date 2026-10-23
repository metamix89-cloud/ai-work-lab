# -*- coding: utf-8 -*-
"""3편 v2 코드 규칙 자가 시험: 등급 판정 · 품목 이름 정규화 · 정렬 순서. API 호출 없음.
사용: python _scratch/wiki/guard_test.py"""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
for p in ["suppliers/가나공급_단가표.csv", "suppliers/가나공급_공문_2026-10-15.md", "meetings/2026-09-15_경영회의.md", "cs/주간보고_2026-10-19.md",
          "suppliers/구매팀_메모_김과장.md", "cs/FAQ_초안.md", "policies/안내문_재택근무_옛.md", "customers/가나마트_계약조건.md", "customers/상품안내_초안_밀키트.md"]:
    print("%d  %s" % (E.grade_of(p), p))
print()
for s in ["상품/떡볶이소스", "상품/떡볶이-소스-2kg", "상품/떡볶이 소스", "상품/고추장", "상품/냉동-떡갈비-500g", "상품/떡갈비-500g", "거래처/가나공급", "상품/밀키트"]:
    print("%-22s → %s" % (s, E.canon_slug(s)))
files = sorted(glob.glob(os.path.join(E.RAW, "suppliers", "*.*")) + glob.glob(os.path.join(E.RAW, "customers", "*.*")), key=lambda f: (E.grade_of(f), f))
print()
print("등급 순서:", " → ".join("%d:%s" % (E.grade_of(f), os.path.basename(f)[:12]) for f in files))
