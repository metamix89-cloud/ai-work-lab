# EN ep04 lab — context compression strategies (2026-10-22, gpt-4.1-mini)

A 20-turn day with a ValueMart (fictional) buyer; 6 facts settled along the way must appear in the final order confirmation.
Book ch.2 experiment 2-10, re-done in English with US grocery items.

## Files

| File | What it does |
|---|---|
| lab.py | the experiment (usage in the docstring) → results.json · probe.json (S0 × 2, used to set BUDGET) |
| test_grade.py | self-test for the 6 fact checks (no API calls) |
| regrade.py | re-grades saved confirmations with the current fact checks (keeps `kept_first`) |
| summarize.py | facts kept per strategy, `--finals=S2` / `--notes=S6` to read the real outputs |

## Window limit

Uncompressed peak (probe, S0): 31,854 tokens. BUDGET = 27,700 = 87% of it — the same ratio as the Korean run (32,000 of ~36,800).

## Results (facts kept out of 30, after the grader fix)

| Strategy | Kept | Tokens per run | Notes |
|---|---|---|---|
| S0 reference, no limit | 30 | 522K | |
| S1 no compression | 0 | 388K | overflow at turns 19, 15, 14, 14, 17 |
| S2 truncate (last 8 turns) | 20 | 353K | lost payment terms 5/5 and the price-increase date 5/5 (some invented dates: Nov 1 2025, Nov 15) |
| S3 generic summary | 30 | 131K | |
| S4 task-aware summary | 30 | 138K | |
| S5 batch near the limit | 30 | 323K | |
| S6 progress notes | 25 | 367K | lost the price-increase date 5/5; notes held wrong dates (Jan 1, Nov 10) |

- The mac & cheese date survived truncation because the agent pulled the stock sheet again at turn 17.
- Korean run (ep039): truncate 24 · generic 29 · task-aware 29 · batch 30 · notes 23 — same pattern.

## Mistake (shown in the video)

The first "pay on the 15th" check matched any "15". S2#4 wrote a made-up "Frozen Price Increase: Effective November 15" and
"Payment Terms: As per existing contract", and was credited with the payment terms. Fixed to count only a 15 on a payment/month line;
that answer was added to test_grade.py; results re-graded (S2 21 → 20). The Korean ep039 results were re-checked with
04_context_compress/pay15_recheck.py — every credited '15일' was on a payment line, no difference.
