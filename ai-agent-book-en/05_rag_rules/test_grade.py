# -*- coding: utf-8 -*-
"""Grader self-test (no API calls; the embedding cache must exist or OPENAI_API_KEY must be set). Usage: python test_grade.py"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lab import QS, grade

CASES = {   # qid: (right answers, wrong answers)
    "Q1": (["Request PTO at least 3 days in advance with HR-201 (11)."], ["Request PTO 2 weeks in advance."]),
    "Q2": (["Keep it at 0°F or below (25).", "0 °F or colder"], ["Keep it at -18°C or below."]),
    "Q3": (["Up to $1,000 per year (28)."], ["Up to $500 per year."]),
    "Q4": (["$10 per member per month (29)."], ["$100 per member per month."]),
    "Q5": (["It's for registering a USB drive or other external storage (17)."], ["It's the incident report form."]),
    "Q6": (["For life-event leave, like weddings or a death in the family (12)."], ["For PTO requests."]),
    "Q7": (["PU-310 is the vendor registration form (22)."], ["PU-310 is the purchase approval form."]),
    "Q8": (["Within 7 days of returning (7)."], ["Within 14 days."]),
    "Q9": (["Senior Associates are grade B: $70 + $20 for New York = $90 per night (1, 2)."],
           ["Up to $110 per night.", "The grade isn't specified; if they are grade B, $90."]),
    "Q10": (["Managers are grade A, so $1,500 per month (1, 8)."], ["$3,000 per month.", "$1,500 if they are grade A, but the grade is not specified."]),
    "Q11": (["Senior Managers are grade A: $90 per night (1, 2)."], ["$110 per night."]),
    "Q12": (["Directors are grade S: ($120 + $20) × 2 = $280 (1, 2)."], ["$240 in total.", "$180 in total."]),
    "Q13": (["Grade B: $500 per month; over $300 needs the team lead's approval in advance (1, 8)."], ["$1,500 per month; team lead approval."]),
    "Q14": (["At least 2 quotes, approved by the division head (20, 21)."], ["3 quotes, approved by the team lead."]),
    "Q15": (["Up to $12 per meal since July 1, 2026 (35)."], ["Up to $10 per meal (4)."]),
    "Q16": (["Up to 2 days a week (36)."], ["Up to 1 day a week (14)."]),
    "Q17": (["$12, the revised meal limit (35)."], ["$10 (4).", "$13."]),
    "Q18": (["I can't find that in the handbook."], ["The gym is open 6 AM to 10 PM."]),
    "Q19": (["The handbook doesn't mention a holiday bonus."], ["The holiday bonus is 50% of monthly pay."]),
    "Q20": (["I can't find that in the handbook."], ["Yes, dogs are welcome on Fridays."]),
}
ok = n = 0
for qid, kind, q, chk in QS:
    good, bad = CASES[qid]
    for t in good:
        n += 1
        ok += grade(qid, kind, chk, t)
        if not grade(qid, kind, chk, t):
            print("XX should pass:", qid, t)
    for t in bad:
        n += 1
        ok += not grade(qid, kind, chk, t)
        if grade(qid, kind, chk, t):
            print("XX should fail:", qid, t)
print("%d/%d" % (ok, n))
