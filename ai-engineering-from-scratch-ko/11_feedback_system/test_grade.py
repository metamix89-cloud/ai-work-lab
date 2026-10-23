# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
import lab
t = lab.TASKS[2]   # 10/25 — 옛 단가가 정답
good = """| 품목 | 수량 | 단가 | 금액 |
| 떡볶이 소스 2kg | 5 | 73,400원 | 367,000원 (부가세 포함) |
| 고추장 500g | 5 | 46,200원 | 231,000원 (부가세 포함) |
유효기간: 2026-11-08 까지"""
print("정답 기대 ok True:", lab.check(t, good))
bad = good.replace("73,400", "79,270").replace("부가세 포함", "부가세 별도").replace("2026-11-08", "2026-11-09")
print("증상 따라 틀림 기대 단가·부가세·유효기간 실패:", lab.check(t, bad)["fails"])
both = good.replace("73,400원 |", "73,400원 → 79,270원 |")
print("두 값 섞이면 단가 실패 기대:", lab.check(t, both)["fails"])
print("월일 표기 허용:", lab.check(t, good.replace("2026-11-08", "2026년 11월 8일"))["valid"])
