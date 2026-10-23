# -*- coding: utf-8 -*-
"""Summaries for the 100-tools lab. Usage:
  python summarize.py a [results_a.json]     → correct per model × condition × request, and every failure (tools called, answer)
  python summarize.py b [results_b.json]     → fine/risky outcomes per condition, reviewer verdicts, and every failure"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
which = sys.argv[1] if len(sys.argv) > 1 else "a"
fn = sys.argv[2] if len(sys.argv) > 2 else ("results_a.json" if which == "a" else "results_b.json")
with open(os.path.join(HERE, fn), encoding="utf-8") as f:
    res = [r for r in json.load(f) if "error" not in r]
if which == "a":
    tasks = list(dict.fromkeys(r["task"] for r in res))
    for m in ["gpt-4.1-mini", "gpt-4.1-nano"]:
        print("==", m)
        for c in ["ALL", "PRE", "DISC"]:
            rs = [r for r in res if r["model"] == m and r["cond"] == c]
            print("  %-4s %2d/%d  " % (c, sum(r["ok"] for r in rs), len(rs)) +
                  " ".join("%s:%d" % (t, sum(r["ok"] for r in rs if r["task"] == t)) for t in tasks))
    print()
    for r in res:
        if not r["ok"] and r["model"] == "gpt-4.1-mini":
            print("%s %s %s#%d called=%s finds=%s\n    %s" % (r["model"][-4:], r["cond"], r["task"], r["seed"], r["called"], r["finds"],
                                                          r["answer"].replace("\n", " ")[:220]))
else:
    for c in ["NONE", "REVIEW"]:
        rs = [r for r in res if r["cond"] == c]
        print("%s fine run %d/%d · risky stopped %d/%d" % (c, sum(r["ok"] for r in rs if r["kind"] == "ok"), sum(1 for r in rs if r["kind"] == "ok"),
                                                         sum(r["ok"] for r in rs if r["kind"] == "risky"), sum(1 for r in rs if r["kind"] == "risky")))
    for r in res:
        if not r["ok"] or r["blocked"]:
            print("\n%s %s#%d ok=%s executed=%s blocked=%s\n  reviews=%s\n  args=%s\n  %s" % (r["cond"], r["task"], r["seed"], r["ok"], r["executed"],
                                                                                         r["blocked"], r["reviews"], r["args"], r["answer"].replace("\n", " ")[:250]))
