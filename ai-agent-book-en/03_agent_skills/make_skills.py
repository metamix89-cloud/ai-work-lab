# -*- coding: utf-8 -*-
"""EN ep03 lab — writes 9 Yummy Tummy Foods (fictional) work skills under skills/.
Follows the book's experiment 2-6 three-layer layout: SKILL.md frontmatter (layer 1) · body (layer 2) · reference files (layer 3) · bundled script.
Usage: python make_skills.py   (run once before lab.py)"""
import os, shutil, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "skills")

SKILLS = {
"weekly-report-ppt": dict(
 desc="Use when making the weekly sales report as a PowerPoint file (.pptx). Not for monthly reports, external presentations, or text-only summaries.",
 body="""
# Weekly sales report PPT

Builds the weekly report slides the sales team brings to the Friday managers' meeting.

## Slide structure (exactly 5 slides, in this order)
1. Cover — title is `Weekly Sales Report | {period}` (e.g. `Weekly Sales Report | 10/13-10/17`)
2. Sales summary — total sales this week, one line on % of target, one line vs last week
3. By product — one line per product: `Product: actual / target (% of target)`
4. Issues · actions — one line per issue: `Issue → action`
5. Next week — title exactly `Next Week To-Do`, one line per task: `Task (owner)`

## Numbers
- All amounts in **thousands of dollars** with one decimal and a K (e.g. $12.4K). Never write full dollar amounts.
- Percent of target: round to a whole number (e.g. 113%).
- Never invent numbers that are not in the data. If missing, write `no data`.

## How to build it
1. Turn the data into an outline JSON that follows the 5-slide structure above.
   `{"file": "weekly.pptx", "slides": [{"title": "...", "bullets": ["...", "..."]}, ...]}`
2. Call `run_script` on this skill's `scripts/make_ppt.py`, passing the outline JSON as input.
3. If the script reports a slide count other than 5, fix the outline and run it again.
4. Tell the user only the file name and the slide titles.

Read `reference.md` if you need color, font or chart rules. The script defaults are usually enough.
""",
 files={"reference.md": """
# Weekly report design rules (reference)

- Background: dark navy #111318, accent indigo #6366F1, above target green #10B981, below target red #EF4444
- Fonts: titles Pretendard Bold 32pt, body Pretendard 20pt. At most 5 bullets per slide
- Leave a logo space on the cover; no photos
- If a chart is needed, a single bar chart only. No pie charts
- More than 6 products: top 5 + `Other`
- Meeting screens are 16:9. Never 4:3
- Slide numbers bottom right, none on the cover
- Talk time is 3 minutes. One line of speaker notes per slide
""".strip()}),

"return-policy": dict(
 desc="Use to decide whether a customer's return or refund request is allowed and to calculate the refund. Not for exchanges, delivery tracking, or general product questions.",
 body="""
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
""",
 files={"reference/products.md": """
# Yummy Tummy Foods product categories (as of 2026-10)

| Product | Category | Note |
|---|---|---|
| Yummy Tummy Pepperoni Pizza 2-pack | Frozen | |
| Yummy Tummy Mac & Cheese Bake | Frozen | |
| Yummy Tummy Chicken Nuggets 2 lb | Frozen | |
| Yummy Tummy Handmade Burger Patties | Refrigerated | Not frozen despite the name. Keep refrigerated after delivery |
| Yummy Tummy Fresh Salsa | Refrigerated | |
| Yummy Tummy Hummus 2-pack | Refrigerated | |
| Yummy Tummy BBQ Sauce 18 oz | Pantry | |
| Yummy Tummy Cola 12-pack | Pantry | |
| Yummy Tummy Sesame Burger Buns 8-pack | Pantry | |
| Yummy Tummy Holiday Gift Basket | Pantry | over $50 |
| Yummy Tummy Premium Steak Gift Box | Frozen | over $50 |
""".strip()}),

"partner-email": dict(
 desc="Use when replying in the company's name to a business email from a partner (supplier or distributor). Not for internal messages, texts, or customer replies.",
 body="""
# Partner email reply

A reply to a partner becomes an official company record. Follow this format.

## Format
- Subject on the first line: `[Yummy Tummy Foods] Re: {original subject}`
- Greeting: `Dear {contact name},` — if unknown, `Dear Partner,`
- Body: at most 3 paragraphs. Put our position (the conclusion) in the first paragraph
- Write dates as `Tuesday, October 28`
- The signature on the last line is exactly: `Yummy Tummy Foods Sales Support Team | (555) 010-0000`

## Never write
- Anything that confirms prices or contract terms (`we accept`, `we agree`) — only the team lead can confirm
- Other partners' names, internal costs, stock levels
- Emoji or slang

## Common reply types
- Will review and reply: confirm receipt + the date we will answer by
- Request for documents: a list of what we need and by when
- Schedule change: the new date and a one-line reason
"""),

"meeting-minutes": dict(
 desc="Use to turn meeting notes or transcripts into the company's standard meeting minutes. Not for scheduling meetings or making meeting slides.",
 body="""
# Standard meeting minutes

Turns scattered meeting notes into the company's standard minutes.

## Format (this order, these headers)
```
Minutes | {meeting name} | {date}
Attendees: {names}

■ Decisions
- decision 1
■ Action Items
- {task} / {owner} / {due}
■ Next Meeting
- {date · time · agenda}
```

## Rules
- Decisions start with `Agreed to ...`. If something was discussed without a conclusion, it is not a decision
- Every action item needs an owner and a due date. If the notes don't say, write `owner TBD` or `due TBD` — never invent them
- Don't copy who said what
- If the notes have no next meeting, write `- TBD`
- No summary line or greeting before or after
"""),

"product-copy": dict(
 desc="Use when writing short copy for a new product (online store listing or in-store sign). Not for press releases, long product pages, or ad scripts.",
 body="""
# New product copy

Short copy for the online store list and in-store signs.

## Format (exactly 3 lines, nothing else)
Line 1: the product in one sentence — 60 characters max
Line 2: one taste or use — 60 characters max
Line 3: `[Allergens] {allergens in the ingredients}` — required by food labeling rules

## Major allergens (US labeling)
milk, eggs, fish, shellfish, tree nuts, peanuts, wheat, soybeans, sesame
- Soy sauce is usually made from soybeans and wheat → list both
- If none, `[Allergens] None`

## Never write
- `best`, `#1`, `100% natural` (unless verified), `healthy`, any disease or health claims
- Multiple exclamation marks, emoji
"""),

"inventory-alert": dict(
 desc="Use to decide from stock and sales numbers whether each item needs a reorder, and to write the stock alert. Not for sales reports or price questions.",
 body="""
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
"""),

"expense-report": dict(
 desc="Use to calculate a business-trip expense reimbursement under company policy. Not for corporate card statements or payroll questions.",
 body="""
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
"""),

"haccp-check": dict(
 desc="Use to fill in or summarize the daily food-safety (HACCP) checklist for the plant or warehouse. Not for marketing or customer service.",
 body="""
# HACCP daily checklist

Records the plant and warehouse hygiene check in the same format every day.

## Items
1. Freezer temperature: 0°F or below (record every 2 hours)
2. Fridge temperature: 32-41°F
3. Worker hygiene: uniform · cap · mask · handwashing log
4. Foreign objects: metal detector check (start · lunch · end, 3 times)
5. Cleaning: work tables · knives · cutting boards sanitized
6. Pest control: insect lights checked, doors closed

## Record format
`{item} | {standard} | {measured} | pass/fail | {action}`
- If it fails, always write the action and the re-measured value
- Temperatures to one decimal

## When something fails
- Freezer above 5°F for more than 30 minutes: call the quality lead immediately
- Metal detector down: hold everything produced in that period
"""),

"onboarding-guide": dict(
 desc="Use to make a new hire's first-week schedule, system account and training guide. Not for job postings or performance reviews.",
 body="""
# New hire first week

One page with the first-week schedule and account setup.

## First week (default)
- Mon: morning paperwork · security pledge, afternoon system accounts
- Tue: company intro · product training (pantry · refrigerated · frozen lines)
- Wed: warehouse tour, food safety training (HACCP basics)
- Thu: team handover · mentor meeting
- Fri: first-week review, questions

## Accounts
- IT sets up email, chat and groupware on Monday afternoon
- Change the password after the first login and turn on 2-step verification
- Never send passwords by chat or email

## Guide format
- Title: `Welcome to Yummy Tummy Foods, {name}`
- Day-by-day table → accounts → mentor's name and how to reach them
"""),
}


def main():
    for name, s in SKILLS.items():
        d = os.path.join(ROOT, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(f"---\nname: {name}\ndescription: {s['desc']}\n---\n" + textwrap.dedent(s["body"]).strip() + "\n")
        for rel, txt in s.get("files", {}).items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(txt + "\n")
    sd = os.path.join(ROOT, "weekly-report-ppt", "scripts")
    os.makedirs(sd, exist_ok=True)
    shutil.copy(os.path.join(HERE, "make_ppt.py"), sd)
    print("skills:", len(SKILLS))


if __name__ == "__main__":
    main()
