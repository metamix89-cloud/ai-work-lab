---
name: weekly-report-ppt
description: Use when making the weekly sales report as a PowerPoint file (.pptx). Not for monthly reports, external presentations, or text-only summaries.
---
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
