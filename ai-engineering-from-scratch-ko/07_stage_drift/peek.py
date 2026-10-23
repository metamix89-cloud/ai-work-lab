# -*- coding: utf-8 -*-
"""결과 들여다보기: python peek.py [조건] [요청...]  예) python peek.py B R3 R4"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
cond = sys.argv[1] if len(sys.argv) > 1 else "B"
reqs = sys.argv[2:] or ["R1", "R2", "R3", "R4", "R5"]
for r in rs:
    if r["cond"] == cond and r["req"] in reqs:
        calls = [(n, str(list(a.values())[0])[:60]) for n, a in r["calls"] if n != "reply"]
        print(r["req"], "위험" if r["risky"] else "-", calls)
        print("    ", r["reply"][:240].replace("\n", " "))
