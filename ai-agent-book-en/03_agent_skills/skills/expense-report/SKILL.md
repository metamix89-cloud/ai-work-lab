---
name: expense-report
description: Use to calculate a business-trip expense reimbursement under company policy. Not for corporate card statements or payroll questions.
---
# Travel expense reimbursement

Calculates an employee's trip expenses under company policy.

## Policy
- Transportation: actual cost (with receipts only)
- Lodging: up to $70.00 per night. The employee pays anything above
- Meals: up to $10.00 per meal (meals with receipts only). The employee pays anything above
- Per diem: $20.00 per trip day (no receipt needed, departure and return days both count)
- Spending without a receipt is excluded, except the per diem

## Reply format
- One line per item: `Transportation: ... = $N`
- One line per excluded item, with the reason
- The last line is exactly: `Total reimbursement: $N` (two decimals, comma for thousands)
