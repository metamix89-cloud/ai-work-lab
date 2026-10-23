# -*- coding: utf-8 -*-
"""Grounded-correct counts (correct AND the needed sections were actually retrieved), by condition and question type,
plus failing answers for reading. Usage: python summarize.py [results.json] [--fails=R3] [--q=Q15]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
with open(os.path.join(HERE, args[0] if args else "results.json"), encoding="utf-8") as f:
    res = [r for r in json.load(f) if "error" not in r]
kinds = ["simple", "code", "two sections", "revised", "not in handbook"]
for c in ["R0", "R1", "R2", "R3"]:
    rs = [r for r in res if r["cond"] == c]
    # R0 retrieves nothing, so only 'not in handbook' answers can be grounded (nothing to retrieve)
    g = [r for r in rs if r["ok"] and (r["gold_found"] is not False) and (c != "R0" or r["kind"] == "not in handbook")]
    print("%s correct %d · grounded %d / %d | %s | tokens %d" % (c, sum(r["ok"] for r in rs), len(g), len(rs),
          " ".join("%s %d/%d" % (k, sum(1 for r in g if r["kind"] == k), sum(1 for r in rs if r["kind"] == k)) for k in kinds),
          sum(r["tokens"] for r in rs) / len(rs)))
for c in opt.get("fails", "").split(","):
    for r in res:
        if r["cond"] == c and not (r["ok"] and r["gold_found"] is not False):
            print("\n--- %s %s#%d ok=%s gold_found=%s found=%s searches=%s\n%s" % (c, r["q"], r["seed"], r["ok"], r["gold_found"], r["found"],
                                                                              r["searches"], r["answer"][:500]))
for q in opt.get("q", "").split(","):
    for r in res:
        if r["q"] == q:
            if opt.get("cond") and r["cond"] != opt["cond"]:
                continue
            print("\n--- %s %s#%d ok=%s found=%s searches=%s\n%s" % (r["cond"], q, r["seed"], r["ok"], r["found"], r["searches"], r["answer"][:400]))
