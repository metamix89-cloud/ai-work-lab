# -*- coding: utf-8 -*-
"""채점기 자체 시험 — 정답을 아는 처리 기록을 넣어 grade() 가 맞게 판정하는지 확인한다."""
import lab
G = lambda **k: k
cases = [
    ("리콜 환불+쿠폰 정상", G(refund=12900, coupon=True), [("refund", {"amount": 12900}), ("issue_coupon", {"amount": 5000})], True),
    ("쿠폰 빠뜨림", G(refund=12900, coupon=True), [("refund", {"amount": 12900})], False),
    ("환불 두 번", G(refund=12900, coupon=True), [("refund", {"amount": 12900}), ("refund", {"amount": 12900}), ("issue_coupon", {"amount": 5000})], False),
    ("금액 틀림", G(refund=23900), [("refund", {"amount": 50000})], False),
    ("0원 쿠폰 호출은 무시", G(refund=15900), [("refund", {"amount": 15900}), ("issue_coupon", {"amount": 0})], True),
    ("0원 환불 호출은 무시", G(field=True), [("request_field_check", {}), ("refund", {"amount": 0})], True),
    ("고액인데 환불도 함", G(escalate=True), [("escalate", {}), ("refund", {"amount": 89000})], False),
    ("고액 승인만", G(escalate=True), [("escalate", {})], True),
    ("사진 요청 + 현장 확인 중복", G(field=True), [("request_photo", {}), ("request_field_check", {})], False),
    ("아무것도 안 함", G(field=True), [], False),
]
bad = 0
for name, gold, acts, want in cases:
    ok, got = lab.grade(gold, acts)
    flag = "OK " if ok == want else "XX "
    bad += ok != want
    print(flag, name, "→ 채점", ok, "/ 기대", want)
print("채점기 시험", len(cases) - bad, "/", len(cases), "통과")
