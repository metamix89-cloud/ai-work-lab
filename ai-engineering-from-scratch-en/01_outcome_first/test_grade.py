# -*- coding: utf-8 -*-
"""Test the grader first, on report shapes whose answers we know."""
import lab
R = lab.RISK
cases = [
 ("table + status column", "| Code | Item | On hand | Status |\n|---|---|---|---|\n" + "\n".join(
   f"| {r[0]} | {r[1]} | {r[3]} | {'STOCKOUT RISK' if r[0] in R else 'OK'} |" for r in lab.ROWS), R),
 ("list under a risk heading", "## 1. Items that run out before the next delivery\n- Pepperoni Pizza 2-pack (0 on hand)\n- Cheese Pizza: 1.1 days of cover\n- Chicken Nuggets 2 lb\n- Fresh Pasta\n- Cola 12-pack\n- Chicken Pot Pie Kit\n\n## 2. Other items\n- Fresh Salsa 16 oz: delivery tomorrow\n- Handmade Burger Patties: delivery tomorrow", R),
 ("safe sentences are not flags", "Fresh Salsa 16 oz is low but a delivery arrives tomorrow, so there is no risk of a shortage.\nHandmade Burger Patties: stock is sufficient.", set()),
 ("expiry warning is not a flag", "### Expiring soon - watch\n- Fresh Salsa 16 oz, 40 cases\n- Fresh Pasta 1 lb, 25 cases", set()),
 ("risk section after an expiry section", "### Expiring within 30 days\n- Fresh Salsa 16 oz, 40 cases\n### Stockout risk\n- Pepperoni Pizza 2-pack: out of stock\n- Cola 12-pack", {"F101", "D307"}),
 ("pizza sauce vs. pizza", "- Pizza Sauce 1 gal: shortage expected", {"D305"}),
 ("bold heading", "**Urgent reorder needed**\n1. Pepperoni Pizza 2-pack\n2. Cheese Pizza 2-pack\n\n**Items with enough stock**\n- Hot Cocoa Gift Tin", {"F101", "F102"}),
 ("bold heading + lines", "**Items expected to run short:**\n- F103 Chicken Nuggets\n- C202 Fresh Pasta\n**Normal items:**\n- D301 BBQ Sauce", {"F103", "C202"}),
 ("'shorter' is not a risk word", "Chicken Nuggets: days of cover 8.5 is shorter than the 10 days until delivery -> STOCKOUT RISK\nBBQ Sauce: cover is longer, no issue", {"F103"}),
 ("no-space table cell", "F101\tPepperoni Pizza 2-pack\t0\t85\tREORDER\nC201\tFresh Salsa 16 oz\t180\t64", {"F101"}),
 ("'Needs order?' YES/NO column under a risk heading", "**[Goal] Identify items running out before next delivery**\n| Code | Item | Needs Order? |\n| F101 | Pepperoni Pizza 2-pack | YES |\n| C201 | Fresh Salsa 16 oz | NO |", {"F101"}),
 ("'Monitor (no immediate order needed)' list", "**Monitor (no immediate order needed):**\n- Fresh Salsa (C201)\n- Taco Night Kit (M403)", set()),
]
ok = 0
for name, rep, want in cases:
    got = lab.flagged(rep)
    good = got == set(want)
    ok += good
    print("OK " if good else "XX ", name, "" if good else f"got={sorted(got)} want={sorted(want)}")
print(f"{ok}/{len(cases)}")
print("cost leak ($46.20 and $41.2):", lab.leaked_price("BBQ Sauce unit cost $46.20; pizza $41.2 per case"), "| none expected:", lab.leaked_price("1,500 cases, 141.20 is not a cost; days of cover 17.5; 210 / 12 = 17.50"),
      "| copied column (3+ values) expected:", len(lab.leaked_price("| 41.20 |\n| 38.90 |\n| 52.30 |")))
rep = "\n".join(f"| {r[0]} | {r[1]} | {r[3]/r[4]:.2f} | {lab.arrive_days(r[5])} |" for r in lab.ROWS)
print("verifiable 6 expected:", lab.evidence_ok(rep), "| non-goals [] expected:", lab.nongoal("Expiry management is excluded (separate meeting)."),
      "| non-goals ['expiry'] expected:", lab.nongoal("## Expiring soon\n- Fresh Salsa 40 cases"), "| 'sales' as shipments not counted:", lab.nongoal("daily sales of 85 cases"))
