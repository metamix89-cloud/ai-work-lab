# -*- coding: utf-8 -*-
"""Grader self-test for the 6 facts (no API calls). Usage: python test_grade.py"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import FACTS

GOOD = ("Order confirmation\n- Pepperoni Pizza 2-pack: 150 cases\n- Ship to: ValueMart Distribution Center 2, Dayton, OH\n"
        "- Frozen deliveries: Tuesdays and Thursdays\n- Frozen price increase: applies from December 1\n"
        "- Payment: invoice at month-end, cash on the 15th of the following month\n- Mac & Cheese Bake: can ship from November 12")
GOOD2 = "150 cases · DC 2 · Tue/Thu · 12/1 · paid on the 15th · ships 11/12"
BAD = ("- Pepperoni Pizza 2-pack: 120 cases\n- Ship to: main store\n- Frozen deliveries: Mon/Wed/Fri\n- Price increase from November 1\n"
       "- Payment: net 30\n- Mac & Cheese Bake: ships from November 5")
BAD2 = "Frozen Price Increase:\nEffective November 15\n\nPayment Terms:\nAs per existing contract"   # a real run: the 15 is not a payment day
GOOD2 = "150 cases · DC 2 · Tue/Thu · 12/1\nPayment: paid on the 15th of the next month · ships 11/12"
ok = 0
for name, f in FACTS:
    a, b, c, d = f(GOOD), f(GOOD2), f(BAD), f(BAD2)
    good = a and b and not c and not d
    ok += good
    print("OK " if good else "XX ", "%-22s good=%s good2=%s bad=%s bad2=%s" % (name, a, b, c, d))
print("%d/%d" % (ok, len(FACTS)))
