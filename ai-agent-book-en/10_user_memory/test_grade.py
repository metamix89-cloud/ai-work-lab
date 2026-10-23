# -*- coding: utf-8 -*-
"""Answer-check self-test (no API calls; needs only that lab.py imports). Usage: python test_grade.py"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import Q

CASES = {  # qid: (right answers, wrong answers)
    "L1-1": (["The account code is VM-2207."], ["I don't know the account code."]),
    "L1-2": (["Invoices go to ap@valuemart.example."], ["Send them to sam.park@valuemart.example."]),
    "L1-3": (["We quoted $102.00 per case, 3% off at 100+ cases."], ["$120 per case."]),
    "L1-4": (["They ordered 200 Holiday Gift Basket B."], ["They ordered 30 sets."]),
    "L2-1": (["Frozen goes to Dayton DC 2."], ["Send it to Columbus main DC.", "I don't know."]),
    "L2-2": (["Tuesdays and Thursdays (it was Mon/Wed/Fri in August, then changed back)."], ["They currently take frozen on Monday, Wednesday and Friday."]),
    "L2-3": (["Sam Park, extension 4417, sam.park@valuemart.example."], ["Jenna Lee, ap@valuemart.example."]),
    "L2-4": (["Cash on December 10th (terms changed from the 15th to the 10th in October).", "On the 10th of December."],
             ["They pay on the 15th of the following month.", "On the 15th, or maybe the 10th."]),
    "L3-1": (["Hi Sam, Dayton DC 2 only takes frozen on Tuesdays and Thursdays, so Monday 10/26 isn't possible. Can we deliver Tuesday 10/27?"],
             ["Confirmed: 100 cases of pepperoni pizza to Dayton on Monday 10/26."]),
    "L3-2": (["Add allergen stickers to the nut sets, and ship them to the Columbus main DC (pantry)."], ["50 nut sets ready for Dayton."]),
    "L3-3": (["Send the new food safety certificate before it expires on October 31.",
              "The HACCP food safety certificate expires on 2026-10-31, so send a new one before November."],   # a real answer the first check missed
             ["Just confirm the delivery date."]),
    "L3-4": (["Frozen → Dayton DC 2, on Tuesdays or Thursdays."], ["Ship to Columbus on Monday."]),
}
ok = n = 0
for qid, lv, q, chk in Q:
    good, bad = CASES[qid]
    for t in good:
        n += 1
        ok += chk(t)
        if not chk(t):
            print("XX should pass:", qid, t)
    for t in bad:
        n += 1
        ok += not chk(t)
        if chk(t):
            print("XX should fail:", qid, t)
print("%d/%d" % (ok, n))
