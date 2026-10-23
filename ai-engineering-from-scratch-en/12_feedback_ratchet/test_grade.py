# -*- coding: utf-8 -*-
import lab
good = """| Signal no. | Cause | Layer | Change | Owner | Priority | How to verify | Review date · retire condition |
|---|---|---|---|---|---|---|---|
| 3, 9, 12, 10 | Lookup by phone number alone mixes family orders | Policy / permissions | Lookup tool requires order id or name + phone | Alex (support lead) | High | 0 cross-customer exposures in 4 weeks | 11/20 · retire when 0 for 8 weeks |
| 1 | Refunds over $50 need approval | Policy / permissions | Refund tool caps at $50 without an approval token | Morgan | High | 0 refunds over $50 without approval | 11/20 · keep |
| 5 | No timeout on the carrier API | Runtime | 10 s timeout + max 1 retry | Taylor | Medium | lookups per case <= 2 | 11/20 · - |
| 8 | After-the-fact coupon review is stale | Eval | Replace with a weekly 5% sample audit | Alex | Low | violations stay at 0 | 12/01 · remove the audit after 8 clean weeks |"""
g = lab.grade(good, "B")
print("dup True · fix1 struct True · fix5 runtime True · retire8 True · owners 4 · retire_cond 4 expected:", g)
bad = """| Signal no. | Action | Owner | Priority |
|---|---|---|---|
| 1 | Add a reminder to the prompt to get approval over $50 | AI team, Support team | High |
| 3 | Train the AI to check names | Support | Medium |
| 9 | Add guidance about phone lookups | Support | Medium |
| 5 | Investigate slow API | IT | Low |
| 8 | Keep the control, add automation review | Ops | Low |"""
g = lab.grade(bad, "A")
print("dup False · fix1 prompt only True · fix5 runtime False · retire8 False expected:", g)
