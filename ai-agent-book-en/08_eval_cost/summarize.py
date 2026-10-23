# -*- coding: utf-8 -*-
"""Summaries for the evaluation lab. Usage:
  python summarize.py pass     → per-case successes out of 5 for each condition
  python summarize.py judge    → judge agreement, and every wrong refund a judge passed (case, answer, judge's last words)"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
which = sys.argv[1] if len(sys.argv) > 1 else "pass"
if which == "pass":
    with open(os.path.join(HERE, "results_pass.json"), encoding="utf-8") as f:
        res = [r for r in json.load(f) if "error" not in r]
    for c in ["PROMPT", "CODE"]:
        rs = [r for r in res if r["cond"] == c]
        cases = list(dict.fromkeys(r["case"] for r in rs))
        print(c, " ".join("%s:%d" % (k[-2:], sum(r["ok"] for r in rs if r["case"] == k)) for k in cases))
else:
    with open(os.path.join(HERE, "results_judge.json"), encoding="utf-8") as f:
        out = json.load(f)
    for j in ["j1", "j2"]:
        print(j, "agree %d/%d · failed right ones %d · passed wrong ones %d (wrong refunds %d)" % (
            sum(o[j] == o["truth"] for o in out), len(out), sum((not o[j]) and o["truth"] for o in out),
            sum(o[j] and not o["truth"] for o in out), sum(o[j] and o["wrong_money"] for o in out)))
    from collections import Counter
    print("j1 scores on right answers:", dict(Counter(o["j1_score"] for o in out if o["truth"])))
    for j in ["j2", "j1"]:
        print("\n== %s passed these wrong refunds" % j)
        for o in out:
            if o[j] and o["wrong_money"]:
                print("  %s %s#%d | %s | judge: %s" % (o["cond"], o["case"], o["seed"], o["answer"].replace("\n", " ")[:110],
                                                    o[j + "_text"].replace("\n", " ")[-120:]))
