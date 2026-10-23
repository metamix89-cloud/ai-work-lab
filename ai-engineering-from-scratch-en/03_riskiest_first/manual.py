# -*- coding: utf-8 -*-
"""Hand check of the stage-2 decisions (python show.py C decide): did the reasons cite the plan's own pre-set criterion (85-90%)?
The regex 'cites' flagged C2 because of the word 'agreed' ("The AI agreed with Quality 82%"). Read by a person: none of the 10 C decisions mentions
its own 85-90% criterion - every one says '82% is promising, but 9% false positives'. Stored as cites_manual."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "results.json")
rs = json.load(open(p, encoding="utf-8"))
for r in rs:
    r["cites_manual"] = False
json.dump(rs, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for c in "ABC":
    x = [r for r in rs if r["cond"] == c]
    print(c, "cites (regex)", sum(1 for r in x if r.get("cites")), "| cites (hand)", sum(1 for r in x if r["cites_manual"]), "| plans with a criterion", sum(1 for r in x if r["thr"]))
