# -*- coding: utf-8 -*-
"""Re-grade saved answers with the current checks (no API calls); keeps the first grade in 'ok_first'.
Used after the L3-3 date-format fix (see NOTES.md). Usage: python regrade.py"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import Q

chk = {qid: f for qid, lv, q, f in Q}
path = os.path.join(HERE, "results.json")
with open(path, encoding="utf-8") as f:
    res = json.load(f)
for r in res:
    for a in r["answers"]:
        ok = chk[a["q"]](a["answer"])
        a.setdefault("ok_first", a["ok"])
        if ok != a["ok"]:
            print("%s#%d %s  %s → %s" % (r["cond"], r["seed"], a["q"], a["ok"], ok))
        a["ok"] = ok
with open(path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
for c in ["M0", "M1", "M2", "M3"]:
    A = [a for r in res if r["cond"] == c for a in r["answers"]]
    print(c, "correct", sum(a["ok"] for a in A), "/", len(A), "| L3", sum(a["ok"] for a in A if a["level"] == 3), "/ 12")
