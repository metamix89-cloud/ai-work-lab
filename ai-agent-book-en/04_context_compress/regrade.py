# -*- coding: utf-8 -*-
"""Re-grade the saved final confirmations with the current FACTS (no API calls). Keeps the first grade in 'kept_first'.
Used after the 'pay on the 15th' grader fix (see NOTES.md). Usage: python regrade.py [results.json]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import FACTS

path = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "results.json")
with open(path, encoding="utf-8") as f:
    res = json.load(f)
for r in res:
    if "error" in r:
        continue
    kept = [n for n, f in FACTS if f(r["final"])]
    r.setdefault("kept_first", r["kept"])
    if kept != r["kept"]:
        print("%s#%d  %s → %s" % (r["strategy"], r["seed"], r["kept"], kept))
    r["kept"], r["n_kept"] = kept, len(kept)
with open(path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
for s in dict.fromkeys(r["strategy"] for r in res):
    rs = [r for r in res if r["strategy"] == s and "error" not in r]
    print(s, "facts kept", sum(r["n_kept"] for r in rs), "/", 6 * len(rs))
