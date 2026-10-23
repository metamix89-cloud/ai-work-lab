---
name: inventory-alert
description: Use to decide from stock and sales numbers whether each item needs a reorder, and to write the stock alert. Not for sales reports or price questions.
---
# Stock alert

Takes the warehouse stock sheet and flags whether each item needs a reorder.

## Rule
- Safety stock = recent weekly average sales × 1.5 (round up)
- Current stock < safety stock → reorder
- Current stock ≥ safety stock → OK
- No weekly average → `check needed`

## Alert format (one line per item)
`🔴 Reorder | {item} | stock {N} / safety {M}`
`🟢 OK | {item} | stock {N} / safety {M}`
`⚪ Check needed | {item} | {reason}`

- Reorder items first, then OK items
- Last line: `{k} items to reorder`
- Don't decide order quantities (purchasing does)
