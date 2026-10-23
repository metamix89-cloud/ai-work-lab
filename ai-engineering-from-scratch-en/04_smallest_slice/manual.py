# -*- coding: utf-8 -*-
"""Hand-checked scope classification for the open proposals (P, Q), stored as frozen_manual in results.json.
The code rule 'only ... box damage' also matched Q0's sentence "Testing ONLY BOX DAMAGE ... doesn't cover the biggest uncertainty" - a negation.
All 20 scope parts were read by a person (python show.py P scope / Q scope): every P and Q proposal covered frozen / refrigerated spoilage."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(HERE, "results.json")
rs = json.load(open(p, encoding="utf-8"))
MANUAL = {("Q", 0): True}      # code said False; read by hand: covers all types incl. frozen
for r in rs:
    if r["cond"] in "PQ":
        r["frozen_manual"] = MANUAL.get((r["cond"], r["i"]), r["frozen"])
json.dump(rs, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for c in "PQ":
    x = [r for r in rs if r["cond"] == c]
    print(c, "frozen (code)", sum(r["frozen"] for r in x), "| frozen (hand)", sum(r["frozen_manual"] for r in x), "/", len(x))
