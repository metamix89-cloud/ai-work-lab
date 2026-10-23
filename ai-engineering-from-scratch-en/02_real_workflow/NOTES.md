# EN es02 lab notes (2026-10-23, gpt-4.1-mini, 10 runs per condition)

English re-run of the Korean 02_real_workflow: design "AI automation of customer-support returns (current workflow + what to automate)" at Yummy Tummy Foods (fictional).
- The official manual has 4 steps. The real records (12 log lines, team chat, a rep's notes) hold 7 hidden pieces of work:
  1. photo check in the Quality team Slack channel  2. refunds over $50 get the lead's verbal OK (no approval field)  3. repeat returners in Alex's personal spreadsheet ('watch list' tab)
  4. frozen pickups re-entered on the carrier portal  5. phone intake without an order number (lookup by phone number)  6. Friday 4 pm settlement cutoff -> Monday  7. Alex and Morgan work in different orders
- The lead's interview says "we follow the manual, photos are in the system, 5 minutes each". The logs show 4-13 minutes for simple cases and 1.5-3.5 hours when Quality is involved (R-1021 100 min, R-1035 220 min).

## Files

| File | What it does |
|---|---|
| lab.py | 4 conditions x N runs -> results.json |
| test_grade.py | grader self-test (9 cases) |
| regrade.py | re-grade saved reports (no API calls) |
| show.py | print reports; `auto` / `five` filters print the matching lines |

## Results (results.json)

| Condition | hidden work found (avg /7) | used the interview's '5 min' as fact | designed auto-approval over $50 with no human | evidence tags (avg) | words |
|---|---|---|---|---|---|
| A manual only | 0.0 | (no interview) | 0 | 0 | 556 |
| B + lead interview | 0.2 | 10/10 | 0 | 0 | 592 |
| C + real records | 4.8 | 5/10 | 0 | 0 | 895 |
| D + the lesson's method (evidence, strength, friction, hidden info, authority, exceptions, don't merge) | 6.8 | 1/10 | 0 | 44 | 1,329 |

- Per item (C -> D): Quality photo 10 -> 10 · over-$50 approval 10 -> 10 · personal spreadsheet 8 -> 10 · carrier re-entry 7 -> 9 · phone intake 8 -> 10 · Friday cutoff 5 -> 9 · reps differ **0 -> 10**.
- **B:** "Each return takes roughly 5 minutes" and "Photos are attached by customers in the system and reviewed by reps there" - hearsay written down as the workflow. Nothing hidden was found (2/10 mentioned Quality + photo in a generic way).
- **C:** found most of the hidden work but used '5 minutes' as the baseline in 5/10 ("Reduce average handling time per return (currently ~5 minutes)", "from ~5 minutes to ~1-2 minutes"). Nobody wrote that Alex and Morgan work in different orders (0/10) - the two ways were merged into one flow.
- **D:** marked evidence strength on every step (44 tags per report), wrote the two reps' orders separately 10/10, and only 1/10 kept '5 minutes'.
- **Auto-approval over $50 with no human:** 0 in every condition (same as the Korean run). All designs that mentioned auto-approval limited it to refunds under $50.

## Grader rules changed after reading the outputs (shown in the video)

1. **Carrier re-entry and phone intake were too loose.** The first rules accepted bare "carrier" + "portal/website/manually" and "phone" + "order number", so the manual-only condition scored 5/10 on both from ordinary design talk ("integrate the carrier portal", "customer gives the order number by phone"). Narrowed to the actual hidden facts (re-enter / by hand; no order number / lookup by phone number). A dropped to 0.0, C 5.2 -> 4.8, D 6.9 -> 6.8.
2. **Auto-approval rule caught the correct design.** "auto-approve under $50, over $50 to the lead" sat in the same window as "$50", so C 4 and D 3 were counted as violations. Narrowed to "over / above / more than $50" + auto-approve + no human word. Result: 0 everywhere.
