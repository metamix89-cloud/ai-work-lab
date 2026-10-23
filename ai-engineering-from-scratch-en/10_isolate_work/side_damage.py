# -*- coding: utf-8 -*-
"""Collateral damage: lines in the final document that are in neither the original nor the answer (typos, dropped symbols from re-writing someone else's section).
Usage: python side_damage.py"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
good = lab.DOC.replace("$73.40", "$79.30").replace("$46.20", "$47.50").replace("Snack Gift Box: peanuts", "Snack Gift Box: peanuts, walnuts, almonds") \
    .replace("Sesame Burger Buns 8-pack: soy", "Sesame Burger Buns 8-pack: soy, sesame").replace("by 3 pm", "by 2 pm").replace("within 7 days", "within 14 days")
ok_lines = {l.strip() for l in (lab.DOC + good).splitlines() if l.strip()}
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
for c in ["A", "C", "B", "S"]:
    x = [r for r in rs if r["cond"] == c]
    bad = []
    for r in x:
        odd = [l.strip() for l in r["final"].splitlines() if l.strip() and l.strip() not in ok_lines]
        if odd:
            bad.append((r["i"], odd))
    print(c, "collateral damage %d/%d" % (len(bad), len(x)))
    for i, odd in bad[:4]:
        print("   ", i, odd[:3])
