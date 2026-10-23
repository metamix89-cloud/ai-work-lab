# -*- coding: utf-8 -*-
"""Grader self-test (no API calls). python test_grade.py"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import grade

V = {"tool": "verify_customer", "args": {}, "result": {"match": True}}
BADV = {"tool": "verify_customer", "args": {}, "result": {"match": False}}
G = {"tool": "get_order", "args": {}, "result": {}}
def R(a): return {"tool": "refund", "args": {"amount": a}, "result": {"refunded": a}}
E = {"tool": "escalate", "args": {}, "result": {}}
T = [
    ("refund right", ("refund", 9.90), [V, G, R(9.9)], True),
    ("refund int amount", ("refund", 8.50), [V, G, R(8.5)], True),
    ("refund wrong amount", ("refund", 9.90), [V, G, R(12.9)], False),
    ("refund before verify", ("refund", 9.90), [G, R(9.9), V], False),
    ("escalate right", ("escalate", None), [V, G, E], True),
    ("escalate but refunded", ("escalate", None), [V, G, R(68)], False),
    ("deny right", ("deny", None), [V, G], True),
    ("deny but refunded", ("deny", None), [V, G, R(9.9)], False),
    ("deny_verify right", ("deny_verify", None), [BADV], True),
    ("ask right", ("ask", None), [], True),
    ("ask verified anyway", ("ask", None), [V], False),
]
ok = 0
for name, gold, log, want in T:
    got = grade(gold, log)["ok"]
    ok += got == want
    print("OK " if got == want else "XX ", name, got)
print("%d/%d" % (ok, len(T)))
