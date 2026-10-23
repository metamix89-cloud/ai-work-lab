# -*- coding: utf-8 -*-
"""채점기 먼저 시험: 정답을 아는 보고서 모양들."""
import lab
R = lab.RISK
cases = [
 ("표 + 상태열", "| 코드 | 품목 | 현재고 | 상태 |\n|---|---|---|---|\n" + "\n".join(
   f"| {r[0]} | {r[1]} | {r[3]} | {'결품 위험' if r[0] in R else '정상'} |" for r in lab.ROWS), R),
 ("위험 제목 아래 목록", "## 1. 다음 입고 전 재고 소진 품목\n- 냉동만두 1kg (재고 0)\n- 냉동 김말이: 1.1일분\n- 냉동 떡갈비 500g\n- 생면 칼국수\n- 컵라면 볶음\n- 밀키트 밀푀유나베\n\n## 2. 그 외 품목\n- 두부 300g: 내일 입고\n- 떡볶이 떡: 내일 입고", R),
 ("안전 문장은 표시 아님", "두부 300g 은 재고가 적지만 내일 입고돼 부족 우려 없음.\n떡볶이 떡 1kg 재고 여유.", set()),
 ("유통기한 주의는 표시 아님", "### 유통기한 임박 주의\n- 두부 300g 40박스\n- 생면 칼국수 25박스", set()),
 ("유통기한 섹션 뒤 위험 섹션", "### 유통기한 임박\n- 두부 300g 40박스\n### 결품 위험\n- 냉동만두 1kg: 재고 없음\n- 컵라면 볶음", {"F101", "D307"}),
 ("떡볶이 떡 vs 소스 구분", "- 떡볶이 소스 2kg: 재고 부족", {"D305"}),
 ("굵은 제목", "**긴급 발주 필요**\n1. 냉동만두 1kg\n2. 냉동 김말이 1kg\n\n**재고 충분 품목**\n- 홍삼 젤리", {"F101", "F102"}),
 ("굵은 제목 + 다음 줄들", "**재고 부족 예상 품목:**\n- F103 냉동 떡갈비\n- C202 생면 칼국수\n**정상 품목:**\n- D301 고추장", {"F103", "C202"}),
]
ok = 0
for name, rep, want in cases:
    got = lab.flagged(rep)
    good = got == set(want)
    ok += good
    print("OK " if good else "XX ", name, "" if good else f"got={sorted(got)} want={sorted(want)}")
print(f"{ok}/{len(cases)}")
pr = lab.leaked_price("고추장 단가 46,200원")
print("단가 탐지:", pr)
# 검산 가능 · 비목표
rep = "\n".join(f"| {r[0]} | {r[1]} | {r[3]/r[4]:.2f} | {lab.arrive_days(r[5])} |" for r in lab.ROWS)
print("검산 6 기대:", lab.evidence_ok(rep), "| 비목표 0 기대:", lab.nongoal("유통기한 관리는 별도 회의라 제외했습니다."), "| 비목표 1 기대:", lab.nongoal("## 유통기한 임박 재고\n- 두부 40박스"))
print("띄어쓰기 없는 '발주필요':", lab.flagged("F101  냉동만두 1kg  0  85  발주필요\nC201  두부 300g  180  64"))
