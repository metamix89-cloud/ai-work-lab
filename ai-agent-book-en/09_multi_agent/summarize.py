# -*- coding: utf-8 -*-
"""Per-case results and every failure (actions, review, handoff notes). Usage: python summarize.py [results.json] [--cond=SELF] [--case=YT-5009]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
with open(os.path.join(HERE, args[0] if args else "results.json"), encoding="utf-8") as f:
    res = [r for r in json.load(f) if "error" not in r]
cases = list(dict.fromkeys(r["case"] for r in res))
for c in ["SOLO", "CHAIN", "SELF", "VERIFY"]:
    rs = [r for r in res if r["cond"] == c]
    print("%-6s %2d/%d  " % (c, sum(r["ok"] for r in rs), len(rs)) + " ".join("%s:%d" % (k[-2:], sum(r["ok"] for r in rs if r["case"] == k)) for k in cases))
for r in res:
    if opt.get("cond") and r["cond"] != opt["cond"]:
        continue
    if opt.get("case") and r["case"] != opt["case"]:
        continue
    if r["ok"] and not opt.get("case"):
        continue
    print("\n--- %s %s#%d ok=%s wrong_money=%s\n  got=%s gold=%s\n  log=%s" % (r["cond"], r["case"], r["seed"], r["ok"], r["wrong_money"], r["got"], r["gold"], r["log"]))
    if r["review"]:
        print("  review:", r["review"].replace("\n", " ")[:300])
    for n in r["notes"]:
        print("  note:", n.replace("\n", " ")[:300])
