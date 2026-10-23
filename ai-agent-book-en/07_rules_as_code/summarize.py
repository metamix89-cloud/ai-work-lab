# -*- coding: utf-8 -*-
"""Summaries for the rules-as-code lab. Usage:
  python summarize.py a [--case=YT-4010] [--cond=PROMPT] [--model=nano]   → per-case results; with --case, every run's refunds, refusals, answer
  python summarize.py b [--q=B3]                                          → per-question results; with --q, values, SQL and answers"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
which = sys.argv[1] if len(sys.argv) > 1 else "a"
opt = dict(a[2:].split("=", 1) for a in sys.argv[2:] if a.startswith("--") and "=" in a)
with open(os.path.join(HERE, "results_a.json" if which == "a" else "results_b.json"), encoding="utf-8") as f:
    res = [r for r in json.load(f) if "error" not in r]
if which == "a":
    cases = list(dict.fromkeys(r["case"] for r in res))
    for m in ["gpt-4.1-nano", "gpt-4.1-mini"]:
        for c in ["PROMPT", "CODE"]:
            rs = [r for r in res if r["model"] == m and r["cond"] == c]
            print("%-12s %-6s %2d/%d wrong-out %2d  " % (m, c, sum(r["ok"] for r in rs), len(rs), sum(r["wrong_money"] for r in rs)) +
                  " ".join("%s:%d" % (k[-2:], sum(r["ok"] for r in rs if r["case"] == k)) for k in cases))
    for r in res:
        if opt.get("case") and r["case"] != opt["case"]:
            continue
        if opt.get("cond") and r["cond"] != opt["cond"]:
            continue
        if opt.get("model") and opt["model"] not in r["model"]:
            continue
        if opt.get("case") or opt.get("cond"):
            print("\n%s %s %s#%d ok=%s refunds=%s escalated=%s rejected=%s mismatch=%s\n  %s" % (
                r["model"][-4:], r["cond"], r["case"], r["seed"], r["ok"], r["refunds"], r["escalated"], r["rejected"], r["mismatch"],
                r["answer"].replace("\n", " ")[:300]))
else:
    qs = list(dict.fromkeys(r["q"] for r in res))
    for m in ["gpt-4.1-nano", "gpt-4.1-mini"]:
        for c in ["TABLE", "SQL", "SQL2"]:
            rs = [r for r in res if r["model"] == m and r["cond"] == c]
            print("%-12s %-5s %2d/%d tokens %5d  " % (m, c, sum(r["ok"] for r in rs), len(rs), sum(r["tokens"] for r in rs) / len(rs)) +
                  " ".join("%s:%d" % (k, sum(r["ok"] for r in rs if r["q"] == k)) for k in qs))
    for r in res:
        if opt.get("q") == r["q"]:
            print("\n%s %s %s#%d ok=%s value=%s gold=%s\n  sql=%s\n  %s" % (r["model"][-4:], r["cond"], r["q"], r["seed"], r["ok"], r["value"], r["gold"],
                                                                       [s[:160] for s in r["sqls"]], r["answer"].replace("\n", " ")[-250:]))
