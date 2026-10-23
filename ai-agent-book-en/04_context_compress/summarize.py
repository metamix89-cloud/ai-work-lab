# -*- coding: utf-8 -*-
"""Which facts survived, per strategy, plus the final confirmations of runs that lost something (to check the grader by reading).
Usage: python summarize.py [results.json] [--finals=S2] [--notes=S6]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import FACTS

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
with open(os.path.join(HERE, args[0] if args else "results.json"), encoding="utf-8") as f:
    res = [r for r in json.load(f) if "error" not in r]
strategies = list(dict.fromkeys(r["strategy"] for r in res))
print("%-4s " % "" + " | ".join("%-20s" % n for n, _ in FACTS))
for s in strategies:
    rs = [r for r in res if r["strategy"] == s]
    print("%-4s " % s + " | ".join("%-20s" % ("%d/%d" % (sum(n in r["kept"] for r in rs), len(rs))) for n, _ in FACTS))
for s in opt.get("finals", "").split(","):
    for r in res:
        if r["strategy"] == s:
            print("\n--- %s#%d kept %d · lost %s · tool calls at the end: %s" % (s, r["seed"], r["n_kept"], [n for n, _ in FACTS if n not in r["kept"]],
                                                                          [c for c in r["calls"] if int(c.split(":")[0]) >= 17]))
            print(r["final"][:1500])
for s in opt.get("notes", "").split(","):
    for r in res:
        if r["strategy"] == s:
            print("\n--- note %s#%d\n%s" % (s, r["seed"], r["notes"][:900]))
