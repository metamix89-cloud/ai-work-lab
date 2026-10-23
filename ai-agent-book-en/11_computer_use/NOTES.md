# EN ep11 lab — an agent that operates a screen (2026-10-23, gpt-4.1-mini)

A fictional back-office page (erp.html) driven with Playwright (Chrome). 5 requests × 3 runs per method + RPA.

## Files

| File | What it does |
|---|---|
| erp.html | the fake back office (stock · purchase order · accounts · orders; dropdowns, a confirm dialog, a pop-up notice, 9 pages of orders) |
| lab.py | `python lab.py selftest` (RPA must pass 5/5, do-nothing must fail 5/5) · `python lab.py DOM,SOM,SHOT 3 results.json` |
| summarize.py | failed runs with actions (`--method=SHOT --task=T1`) |
| element_boxes.py | real positions of key elements, to compare with SHOT clicks |
| make_compare_image.py | the plain vs. number-marked screenshot used in the video |

## Results (successes out of 15)

| Method | Success | Steps | Tokens | Seconds |
|---|---|---|---|---|
| DOM element index | 15 | 6.0 | 4,249 | 11.4 |
| SOM number marks (inside the box) | 13 | 6.6 | 55,867 | 15.7 |
| SHOT screenshot coordinates | 1 | 11.5 | 130,809 | 24.5 |
| RPA replay | 5/5 | — | 0 | 2.71 |

- SHOT T1: item field is y 167–199; clicks at y 202–213 (just below), typing went nowhere; search button clicks at y 204–210.
  Final answer "There are no cases of 'Pepperoni Pizza 2-pack' on hand at Dayton DC" (really 320).
- SOM T2: one run saved 'Mozzarella' instead of 'Pizza Sauce'; one ran out of steps clicking the same dropdown.
- Korean run (ep046): DOM 15 · SOM 6 → 14 after moving the marks inside the box · SHOT 0 · RPA 5/5.
