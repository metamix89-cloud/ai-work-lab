# -*- coding: utf-8 -*-
"""Re-grade saved answers with the current grader (no API calls). The PPT task (T1) keeps its original grade.
Keeps the first grade in 'ok_first' so the change stays visible. Used after the T6 grader fix (see NOTES.md).
Usage: python regrade.py results.json"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import grade_text

path = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "results.json")
with open(path, encoding="utf-8") as f:
    res = json.load(f)
changed = 0
for r in res:
    if "error" in r or r["task"] == "T1":
        continue
    if len(r["answer"]) >= 1500:
        print("warning: answer was cut at 1500 chars —", r["cond"], r["task"], r["seed"])
    ok, note = grade_text(r["task"], r["answer"], r["read"])
    r.setdefault("ok_first", r["ok"])
    if ok != r["ok"]:
        changed += 1
        print("%s %s#%d  %s → %s  %s" % (r["cond"], r["task"], r["seed"], r["ok"], ok, note))
    r["ok"], r["note"] = ok, note
with open(path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print("changed", changed)
