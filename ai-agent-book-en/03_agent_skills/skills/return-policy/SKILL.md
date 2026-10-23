---
name: return-policy
description: Use to decide whether a customer's return or refund request is allowed and to calculate the refund. Not for exchanges, delivery tracking, or general product questions.
---
# Return and refund decision

Used by support agents to decide whether a return is allowed and how much to refund.

## Decision steps
1. Find the product category. **Never guess the category — always look it up in the `reference/products.md` table.**
   Some products have misleading names (e.g. Handmade Burger Patties are refrigerated, not frozen).
2. Check the return window (counted from the delivery day, last day included)
   - Frozen: 7 days · Refrigerated: 3 days · Pantry: 14 days
3. Opened? — opened items can be returned **only for a quality issue**. Change of mind + opened = no.
4. Quality issues (spoiled, foreign object, damaged) can be returned regardless of window or opening.
5. Amount
   - Change of mind: amount paid minus the $3.00 return shipping fee
   - Quality issue: full amount
6. If the amount paid is over $50.00, don't decide — send it to the team lead for approval.

## Reply format (always)
- The first line is exactly one of: `[Decision] Returnable` / `[Decision] Not returnable` / `[Decision] Needs approval`
- Second line: `Refund: $N` (if not returnable, `Refund: $0.00`)
- From the third line: one or two sentences of reasoning. Never promise credits or coupons that are not in the rules.
