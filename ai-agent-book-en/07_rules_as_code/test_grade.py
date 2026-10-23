# -*- coding: utf-8 -*-
"""Self-tests without API calls: the server rule check gives the answer key's result for every case, and the B grader reads 'Answer:' lines.
Usage: python test_grade.py"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import CASES, DB, server_check, grade_b

ok = n = 0
for oid, msg, (kind, amt) in CASES:
    n += 1
    if kind == "refund":
        reason = "quality issue" if DB[oid][4] or "smell" in msg or "plastic" in msg or "bad" in msg else "change of mind"
        good = server_check({"order_id": oid, "amount": amt, "reason": reason})[0]
        bad = server_check({"order_id": oid, "amount": round(amt + 3, 2), "reason": reason})[0]
        passed = good and not bad
    else:   # deny / escalate: no refund may pass the server check, whatever the model claims
        passed = not any(server_check({"order_id": oid, "amount": a, "reason": r})[0]
                         for a in (DB[oid][2], round(DB[oid][2] - 3, 2)) for r in ("change of mind",))
        if kind == "escalate":
            passed = passed and not server_check({"order_id": oid, "amount": DB[oid][2], "reason": "quality issue"})[0]
    ok += passed
    print("OK " if passed else "XX ", oid, kind, amt)

B = [("int", 5, "There are 5.\nAnswer: 5", True), ("int", 4230, "Answer: $4,230", True), ("int", 4230, "Answer: 4240", False),
     ("float", 3.4, "Answer: 3.45 years", True), ("float", 3.4, "Answer: 3.6", False),
     ("str", "Mason Davis", "**Answer: Mason Davis**", True), ("str", "Mason Davis", "Answer: Emma Lee", False), ("int", 5, "five people", False)]
for typ, gold, ans, want in B:
    n += 1
    got = grade_b(typ, gold, ans)
    ok += got == want
    print("OK " if got == want else "XX ", typ, repr(ans[:30]), got)
print("%d/%d" % (ok, n))
