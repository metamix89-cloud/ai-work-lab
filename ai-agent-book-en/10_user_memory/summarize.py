# -*- coding: utf-8 -*-
"""Per-question results and failing answers; --card prints one memory card. Usage: python summarize.py [--cond=M2] [--card]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
opt = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "1") for a in sys.argv[1:] if a.startswith("--"))
with open(os.path.join(HERE, "results.json"), encoding="utf-8") as f:
    res = json.load(f)
qs = [a["q"] for a in res[0]["answers"]]
for c in ["M0", "M1", "M2", "M3"]:
    A = [a for r in res if r["cond"] == c for a in r["answers"]]
    print("%s %2d/%d  " % (c, sum(a["ok"] for a in A), len(A)) + " ".join("%s:%d" % (q, sum(a["ok"] for a in A if a["q"] == q)) for q in qs))
for r in res:
    if opt.get("cond") and r["cond"] != opt["cond"]:
        continue
    for a in r["answers"]:
        if not a["ok"] and (opt.get("cond") or r["cond"] != "M0"):
            print("\n--- %s#%d %s retrieved=%s\n  %s" % (r["cond"], r["seed"], a["q"], a.get("retrieved"), a["answer"].replace("\n", " ")[:400]))
if opt.get("sizes"):
    sys.path.insert(0, HERE)
    os.environ.setdefault("OPENAI_API_KEY", "x")
    from lab import S, full_text
    cards = [len(r["card"]) for r in res if r["cond"] == "M3"]
    print("\nfull history %d chars · memory cards %s chars · card building tokens %s" % (
        len(full_text(S)), cards, [r["card_tokens"] for r in res if r["cond"] == "M3"]))
if opt.get("card"):
    card = next(r["card"] for r in res if r["cond"] == "M3")
    print("\n== memory card (M3 run 0), %d chars\n%s" % (len(card), card[:3000]))
