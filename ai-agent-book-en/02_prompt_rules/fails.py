# -*- coding: utf-8 -*-
"""Summarize results.json: failures per condition and case, with the agent's final reply.
Usage: python fails.py [cond]"""
import collections, json, os, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "results.json"), encoding="utf-8") as f:
    res = json.load(f)
only = sys.argv[1] if len(sys.argv) > 1 else None

for c in "ABCDE":
    if only and c != only:
        continue
    rs = [r for r in res if r["cond"] == c]
    bad = [r for r in rs if not r["ok"]]
    print("== %s  correct %d/%d" % (c, len(rs) - len(bad), len(rs)))
    print("   by reason:", dict(collections.Counter(r["why"] for r in bad)))
    print("   by case:  ", dict(collections.Counter("case%d" % (r["case"] + 1) for r in bad)))
    for r in bad:
        acts = ["%s(%s)" % (l["tool"], l["args"].get("amount", "")) for l in r["log"] if l["tool"] in ("refund", "escalate")]
        print("   - case%d rep%d %-28s %s | %s" % (r["case"] + 1, r["rep"], r["why"], " ".join(acts) or "-", r["final"].replace("\n", " ")[:150]))
