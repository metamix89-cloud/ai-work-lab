# -*- coding: utf-8 -*-
"""Summarize a results file: correct per condition × task, token use, and every failure note.
Usage: python summarize.py [results.json] [--answers=T2]   (--answers prints full replies for one task)"""
import collections, json, os, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
show = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--answers=")), None)
with open(os.path.join(HERE, args[0] if args else "results.json"), encoding="utf-8") as f:
    res = [r for r in json.load(f) if "error" not in r]

conds = list(dict.fromkeys(r["cond"] for r in res))
tasks = list(dict.fromkeys(r["task"] for r in res))
print("task  " + "  ".join("%6s" % c for c in conds))
for t in tasks:
    row = []
    for c in conds:
        rs = [r for r in res if r["cond"] == c and r["task"] == t]
        row.append("%d/%d" % (sum(r["ok"] for r in rs), len(rs)))
    print("%-5s " % t + "  ".join("%6s" % x for x in row))
print()
for c in conds:
    rs = [r for r in res if r["cond"] == c]
    t8 = [r for r in rs if r["task"] == "T8"]
    print("%-3s correct %d/%d · tokens per request %d · first call %d · T8 alone %s · refused by guard %d" % (
        c, sum(r["ok"] for r in rs), len(rs), sum(r["prompt_tokens"] for r in rs) / len(rs),
        sum(r["first_prompt"] for r in rs) / len(rs), round(sum(r["prompt_tokens"] for r in t8) / len(t8)) if t8 else "-",
        sum(r.get("blocked", 0) for r in rs)))
print()
for c in conds:
    for r in res:
        if r["cond"] == c and not r["ok"]:
            print("%s %s#%d  %s  | read=%s" % (c, r["task"], r["seed"], r["note"], ",".join(r["read"]) or "-"))
if show:
    print("\n==== answers for", show)
    for r in res:
        if r["task"] == show:
            print("--- %s#%d %s %s\n%s" % (r["cond"], r["seed"], "OK" if r["ok"] else "XX", r["note"], r["answer"][:600]))
            if r.get("script_input"):
                print("    script input: " + r["script_input"][:300])
            print()
