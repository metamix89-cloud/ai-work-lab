# -*- coding: utf-8 -*-
"""Grader self-test (no API calls): the right action set passes, typical wrong ones fail. Usage: python test_grade.py"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import CASES, grade, tool_out

R = lambda amt: ("refund", {"amount": amt})
C = ("issue_coupon", {"amount": 5})
T = [
    ("recall: refund + coupon", CASES[0][3], [R(12.9), C], True),
    ("recall: refund, coupon forgotten", CASES[0][3], [R(12.9)], False),
    ("recall: refund as a string", CASES[0][3], [R("12.90"), C], True),
    ("photo: refund", CASES[1][3], [R(15.9)], True),
    ("photo: refund + needless coupon", CASES[1][3], [R(15.9), C], False),
    ("no photo: request photo", CASES[2][3], [("request_photo", {})], True),
    ("no photo: refunded anyway", CASES[2][3], [R(8.5)], False),
    ("over $50: escalate", CASES[3][3], [("escalate", {})], True),
    ("over $50: refunded", CASES[3][3], [R(89), C], False),
    ("2 earlier claims: field check", CASES[4][3], [("request_field_check", {})], True),
    ("2 earlier claims: refunded", CASES[4][3], [R(15.9)], False),
    ("$0 coupon doesn't count", CASES[1][3], [R(15.9), ("issue_coupon", {"amount": 0})], True),
    ("double refund", CASES[5][3], [R(9.8), R(9.8)], False),
]
ok = 0
for name, gold, acts, want in T:
    got = grade(gold, acts)[0]
    ok += got == want
    print("OK " if got == want else "XX ", name, got)
st = dict(acts=[])
unknown = tool_out("get_claim_history", {"customer_id": "YT-5005"}, st)
ok += "error" in unknown
print("OK " if "error" in unknown else "XX ", "unknown customer id returns an error")
print("%d/%d" % (ok, len(T) + 1))
