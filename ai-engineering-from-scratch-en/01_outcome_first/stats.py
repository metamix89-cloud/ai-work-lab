# -*- coding: utf-8 -*-
"""Per-condition detail from results.json: which items were falsely flagged / missed, F code errors, D questions. No API calls."""
import collections, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
import lab
HERE = os.path.dirname(os.path.abspath(__file__))
rs = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
for c in sorted({r["cond"] for r in rs}):
    x = [r for r in rs if r["cond"] == c]
    fl, ms = collections.Counter(), collections.Counter()
    for r in x:
        fl.update(r["false"]); ms.update(r["missed"])
    print("==", c, lab.summary(x))
    print("   false flags:", {lab.CORE[k]: v for k, v in fl.most_common()})
    print("   missed     :", {lab.CORE[k]: v for k, v in ms.most_common()})
    print("   cost leaks :", [r["price"] for r in x if r["price"]][:3])
    if c == "F":
        errs = [r for r in x if r["qa"] and r["qa"].get("errors")]
        print("   first code errored:", len(errs), "/", len(x), "| 3 failures:", sum(1 for r in x if r["report"] == "3 failed runs"))
        for r in errs[:3]:
            print("     e.g.", r["qa"]["errors"][0].strip().splitlines()[-1][:160])
    if c == "D":
        for r in x[:3]:
            print("   Q:", (r["qa"]["q"] if r["qa"] else "")[:400].replace("\n", " / "))
