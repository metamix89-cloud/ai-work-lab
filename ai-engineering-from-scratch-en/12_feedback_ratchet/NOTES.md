# EN es12 lab notes (2026-10-23, gpt-4.1-mini, 2 conditions x 10 plans)

English re-run of the Korean 12_feedback_ratchet: the 'AI first response' from episode 6 in week 4 of operation. 12 signals (incidents · complaints · evals · agent corrections · runtime · a request) -> an improvement plan.
- A: "an improvement plan" (signal | action | owner | priority)
- B: the lesson's feedback ratchet - group by cause · earliest layer · one owner · severity x recurrence · change · how to verify · review date · retire condition · checks/permissions over prompt paragraphs · retire stale controls
- Hidden structure: {3, 9, 12, 10} share one cause (lookup by phone number alone) · no. 1 (refunds over $50) -> permissions / a cap · no. 5 (repeated lookups) -> timeout / retry limit · no. 8 (stale coupon review: 0 violations in 12 weeks, 40 agent-minutes a day) -> retire · no. 7 -> backlog

## Results (results.json; rows read by hand where noted)

| | A plain plan | B the ratchet |
|---|---|---|
| rows avg | 9.2 | 7.2 |
| the 4 phone-number signals (3 · 9 · 12 · 10) on one row | 8/10 | 10/10 |
| no. 1 refund incident -> a permission / cap / hard stop | 9/10 | 8/10 (B0, B5 filed it under 'outdated knowledge') |
| no. 5 repeated lookups -> timeout / retry limit | 8/10 | 10/10 |
| no. 8 stale control explicitly retired or reduced (hand) | **0/10** - all 10 wrote "automate ... to reduce agent review time" (the control stays, a tool is added) | **9/10** - "Retire manual coupon reviews; monitor violations", "Replace mandatory coupon reviews with random audits" (B7 merged 1+8 and automated instead) |
| rows with a retire condition | 0 | 5.9 avg (of 7.2) |
| owner cell = several teams ('AI Dev Team / QA', 'Compliance & AI Dev Teams') | 40 of 92 rows (43%) | 14 of 72 (19%) |

- **Different from the Korean run:** the plain English plan already grouped the phone-number signals (8/10 vs 4/10), fixed the refund incident by structure (9 vs 5) and the lookup loop by runtime (8 vs 3). Where it did not move: the stale control - every plain plan kept the after-the-fact coupon review and added automation ("Review and potentially automate coupon approval audit process", "Automate coupon validation to remove manual agent review"); the ratchet retired it 9/10 with the evidence ("given zero violations in 12 weeks") and a retire condition.
- **B's weaknesses:** B0 grouped 1, 2 and 4 under "outdated or incorrect knowledge source" (the $50 refund is a permission problem, not a knowledge one); B5 sent no. 1 to the knowledge base too; B7 merged 1 and 8 into one 'permissions' row and automated the coupon review instead of retiring it. Owner cells were still teams in half the rows ('Knowledge Management Team', 'AI Development Team') - single named roles ('Compliance Manager', 'Engineering Lead') in 21 of 72.
- Regex `retire8` counted "reduce" in "reduce agent review time" as a reduction (A 9/10); read by hand it is automation on top of the control. The table above uses the hand count. owners.py counts joint cells by separators (, / & and).
