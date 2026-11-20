# -*- coding: utf-8 -*-
"""바탕 앱(base/)과 한 실행의 차이를 본다 — 바뀐 줄 목록(diff)과 AI 의 마지막 보고.
사용: python _scratch/s2s/20_feature_regression/show_diff.py M1_1 [main.py|static/index.html] [--report] [--n=3]"""
import difflib
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
run = sys.argv[1]
files = [a for a in sys.argv[2:] if not a.startswith("--")] or ["main.py"]
ctx = next((int(a[4:]) for a in sys.argv if a.startswith("--n=")), 1)
d = os.path.join(HERE, "runs", run)
if "--report" in sys.argv:
    b = json.load(open(os.path.join(d, "build.json"), encoding="utf-8"))
    print("턴 %s · %.0f초 · $%.2f\n%s\n" % (b.get("num_turns"), b.get("wall_s") or 0, b.get("total_cost_usd") or 0, b.get("result")))
for f in files:
    a = open(os.path.join(HERE, "base", f), encoding="utf-8").read().splitlines() if os.path.exists(os.path.join(HERE, "base", f)) else []
    b = open(os.path.join(d, f), encoding="utf-8").read().splitlines()
    print("=====", run, f)
    for line in difflib.unified_diff(a, b, lineterm="", n=ctx):
        print(line[:220])
