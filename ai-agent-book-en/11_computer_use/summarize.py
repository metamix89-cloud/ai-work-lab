# -*- coding: utf-8 -*-
"""Failed runs with their actions and answers. Usage: python summarize.py [--method=SHOT] [--task=T1]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
with open(os.path.join(HERE, "results.json"), encoding="utf-8") as f:
    res = [r for r in json.load(f) if "error" not in r and r["method"] != "RPA"]
for r in res:
    if opt.get("method") and r["method"] != opt["method"]:
        continue
    if opt.get("task") and r["task"] != opt["task"]:
        continue
    if r["ok"] and not opt.get("task"):
        continue
    print("\n--- %s %s#%d ok=%s steps=%d\n  actions=%s\n  answer=%s\n  po=%s" % (r["method"], r["task"], r["seed"], r["ok"], r["steps"],
          r["actions"][:14], r["answer"][:200], r["state"].get("orders_po")))
