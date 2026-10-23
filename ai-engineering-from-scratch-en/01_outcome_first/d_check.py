# -*- coding: utf-8 -*-
"""D condition: what did the AI ask, and what did the team-lead model answer? Counts answers that passed on the cost rule / the carrier rep / the stockout goal."""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
rs = [r for r in json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8")) if r["cond"] == "D" and r["qa"]]
cost = sum(1 for r in rs if re.search(r"cost|price", r["qa"]["a"], re.I))
carrier = sum(1 for r in rs if re.search(r"carrier", r["qa"]["a"], re.I))
goal = sum(1 for r in rs if re.search(r"run out|before (its|their|the) next delivery|stockout", r["qa"]["a"], re.I))
audience = sum(1 for r in rs if re.search(r"audience|who (is|will|sees|reads)|for whom|intended for", r["qa"]["q"], re.I))
print("D runs with questions:", len(rs), "| asked about the audience:", audience, "| answer mentioned cost rule:", cost, "| carrier rep:", carrier, "| stockout goal:", goal)
for r in rs:
    print("--", r["i"], "| found", len(r["found"]), "| false", len(r["false"]), "| A:", r["qa"]["a"][:220].replace("\n", " / "))
