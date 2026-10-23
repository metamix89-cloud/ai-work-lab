# EN ep09 lab — when several agents split the work (2026-10-23, gpt-4.1-mini)

12 fictional quality claims × 4 setups × 3 runs = 144 runs. English re-run of the Korean ep044 lab.

## Files

| File | What it does |
|---|---|
| lab.py | the experiment (`python lab.py SOLO,CHAIN,SELF,VERIFY 3`) → results.json |
| test_grade.py | grader + fake-tool self-test (14/14) |
| summarize.py | per-claim results and every failure with actions, review and handoff notes (`--cond=CHAIN --case=YT-5004`) |

## Results (correct out of 36)

| Setup | Correct | Wrong money out | Tokens |
|---|---|---|---|
| SOLO | 33 | 3 | 3,368 |
| CHAIN | 36 | 0 | 3,675 |
| SELF (text review) | 31 | 5 | 4,512 |
| VERIFY (tool review) | 31 | 5 | 4,749 |

- YT-5004 ($89 steak box, recall lot): rule 2 (recall → refund + coupon) vs rule 5 (over $50 → approval only).
  SOLO refunded + coupon 3/3. CHAIN's quality agent wrote "$89.00, which is over $50.00 … seek team lead approval" → escalate 3/3.
- SELF caught the steak refund ("FIX NEEDED … over $50") but $89 had already gone out; on YT-5006 it caught a wrong coupon and the agent tried issue_coupon(-5).
- VERIFY looked up order/lot/history and still said "NO ISSUES" on YT-5004 3/3.
- Grader leniency (said in the video): one CHAIN escalation used order_id 'L2610-15' (the lot number). grade() only checks that escalate was called.
- Korean run (ep044): SOLO 34 · CHAIN 31 (a handoff note dropped the amount → 50,000 won refunded) · SELF 28 · VERIFY 34.
