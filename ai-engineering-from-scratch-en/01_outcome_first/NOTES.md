# EN es01 lab notes (2026-10-23, gpt-4.1-mini, 10 runs per condition)

English re-run of the Korean 01_outcome_first (same design, same numbers, US grocery items, USD).
Data: Yummy Tummy Foods (fictional) inventory, 26 items, as of Mon 2026-10-26.
- Answer key - 6 items run out before their next delivery: F101 Pepperoni Pizza (0 on hand), F102 Cheese Pizza, F103 Chicken Nuggets (610 cases), C202 Fresh Pasta, D307 Cola 12-pack (1,500 cases), M402 Chicken Pot Pie Kit
- Traps: looks low but safe (Fresh Salsa, Burger Patties - delivery tomorrow; Taco Night Kit - in 3 days); looks plentiful but runs out (Nuggets 610, Cola 1,500)

## Files

| File | What it does |
|---|---|
| lab.py | 6 conditions x N runs -> results.json (`python lab.py`, `TRIALS=10`) |
| test_grade.py | grader self-test on known-answer report shapes (12 cases) |
| regrade.py | re-grade saved reports with the current grader (no API calls) |
| show.py | print reports by condition / index / filter (`perfect`, `leak`) |
| stats.py | which items were falsely flagged or missed per condition, F code errors, D questions |

## Results (results.json)

| Condition | all 6 found, nothing else | found (avg/6) | false flags (sum) | unit cost leaked | non-goals mixed in | words | verifiable (/6) | tokens |
|---|---|---|---|---|---|---|---|---|
| A output only | 0/10 | 1.1 | 2 | 5 | 10 | 842 | 1.5 | 2,268 |
| B output + "thorough" | 0/10 | 1.6 | 13 | 9 | 10 | 1,120 | 1.5 | 2,771 |
| D ask first | 0/10 | 1.3 | 21 | 0 | 5 | 355 | 1.2 | 2,857 |
| C outcome frame (6 boxes) | 1/10 | 1.6 | 9 | 0 | 2 | 416 | 1.3 | 1,614 |
| E frame + how to check | 0/10 | 1.7 | 62 | 0 | 2 | 701 | 5.8 | 2,197 |
| F E + math in code | **10/10** | 6.0 | 0 | 0 | 0 | 255 | 6.0 | 2,640 |

- **A:** every run mixed in non-goals (expiry lists, cost rankings). A0 wrote "Total number of inventory items: 28" (there are 26), called Cola 12-pack the "highest on-hand quantity" and never flagged it. Unit cost column copied in 5/10.
- **B ("thorough and nice to look at"):** longer (1,120 words), cost column copied in 9/10, 13 false flags.
- **D (ask first):** 10/10 asked questions - purpose, audience, format. The team-lead model's answers gave the stockout goal 10/10, the no-costs rule 6/10, the carrier rep 3/10 (d_check.py). Costs were 0, but the reports still found 1.3/6 and had the most false flags of A-D (21: Burger Patties 8, Salsa 7, Taco Kit 7) - knowing the goal did not make the math right.
- **Found items (A-D):** mostly Pepperoni Pizza (0 on hand) and sometimes Cheese Pizza. Nuggets (610) and Cola (1,500) were missed 9-10 times out of 10 in every condition except F.
- **C:** costs 0, non-goals 2, length down to a third. One run (C8) computed "stock at delivery = on hand - daily x days" for every row inline and got all 6 with no false flags - 1/10. C1 listed six items "running out before next delivery" and then marked five of them "Needs order? NO".
- **E:** the numbers were right (verifiable 5.8/6) but the comparison was applied backwards. E0 wrote the rule correctly in its own key ("STOCKOUT RISK = Days of Cover < Days until Next Delivery") and then flagged Fresh Salsa (2.8 days vs delivery in 1) and left Cola (10.7 vs 12) blank. Taco Night Kit flagged 9/10, Salsa and Patties 10/10.
- **F:** 10/10. The code ran on the first try in all 10 runs (the Korean run had 8/10 first-code errors on the as-of line - the English model parsed "As of: 2026-10-26 (Mon)" fine). Output ~255 words, no costs, no non-goals.

## Grader mistakes (shown in the video)

1. **Cost-leak collision:** the first grader matched a 1-decimal cost ("17.5") anywhere - and "days of cover 210 / 12 = 17.5" looked like the $17.50 yogurt cost. F showed "cost leaked 10/10" on its first grading. Fixed: a leak needs money context on the line ($, cost, price) or 3+ different cost values (a copied column). Re-graded: F 0, E 0 (E8's "17.50" was also days of cover).
2. **'Needs order? NO' rows:** under a heading like "[Goal] Identify items running out before next delivery", table rows that said "NO" were counted as flagged. Added '| NO |' and 'no immediate' as safe markers, '| YES |' as a risk marker. C false flags 14 -> 9, D 25 -> 21.
3. **'asked' count:** the summary counted F runs as "asked" because the code-error record was non-empty. Fixed the count only.
