# -*- coding: utf-8 -*-
"""9편 v2 코드 가드 자가 시험(API 없음): merge_conflict_only 가 본문은 지키고 상충 절에만 더하는지.
사용: python _scratch/wiki/conflict_guard_test.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
old = "# 가나마트\n분류: 거래처\n\n## 현재 값\n- 담당: 한 주임 (2026-10-01~)\n- 결제: 익월 25일\n\n## 이력\n- 담당 이 대리 → 한 주임 (2026-10-01)\n\n## ⚠ 상충 · 확인 필요\n- 없음"
new1 = "# 가나마트\n분류: 거래처\n\n## 현재 값\n- 담당: 이 대리\n- 결제: 익월 말\n\n## 이력\n- 담당 이 대리 → 한 주임 (2026-10-01)\n\n## ⚠ 상충 · 확인 필요\n- 영업 메모(10/30): 담당은 이 대리, 결제 익월 말"
new2 = "# 가나마트\n분류: 거래처\n\n## 현재 값\n- 담당: 이 대리\n- 결제: 익월 말\n\n## 이력\n- 담당 이 대리 → 한 주임 (2026-10-01)\n\n## ⚠ 상충 · 확인 필요\n- 없음"
m1, n1 = E.merge_conflict_only(old, new1, 5)
m2, n2 = E.merge_conflict_only(old, new2, 5)
old_nosec = "# 두부\n분류: 상품\n\n## 현재 값\n- 입수: 6개"
m3, n3 = E.merge_conflict_only(old_nosec, "# 두부\n## 현재 값\n- 입수: 4개\n", 5)
checks = [("상충 절 글머리만 더함(본문 그대로)", n1 == 1 and "담당: 한 주임" in m1 and "담당: 이 대리" not in m1.split("## ⚠")[0] and "영업 메모(10/30)" in m1),
          ("상충 절에 안 적고 본문만 바꾸면 바뀐 줄을 상충으로 돌림", n2 == 2 and "담당: 한 주임" in m2 and "본문 반영 거부" in m2 and "익월 말" in m2.split("## ⚠")[1]),
          ("'없음' 줄은 지움", "- 없음" not in m1),
          ("상충 절이 없던 페이지엔 절을 만든다", n3 == 1 and "입수: 6개" in m3 and "## ⚠" in m3 and "입수: 4개" in m3.split("## ⚠")[1]),
          ("같은 글머리는 두 번 안 더함", E.merge_conflict_only(m1, new1, 5)[1] == 0)]
bad = 0
for name, ok in checks:
    print(("OK  " if ok else "!!  ") + name); bad += not ok
print("자가 시험:", "통과" if not bad else "실패 %d" % bad)
sys.exit(1 if bad else 0)
