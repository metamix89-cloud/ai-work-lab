# EN ep01 lab — what makes an agent work (context ablation, book experiment 1-1)

Yummy Tummy Foods (fictional) support agent, written by hand (agent.py, no framework). gpt-4.1-mini.
Question: "Can I return order YT-2417?" — frozen pizza delivered 2026-10-14, today 2026-10-19, frozen = 7 days → returnable until 10/21.

## Files

| File | What it does |
|---|---|
| agent.py | the 30-line core loop + 2 fake tools (`python agent.py` runs one question) |
| ablation.py | 5 setups × N runs → results.json (`python ablation.py 10`) |
| show.py | full answers and tool calls for one setup, for grading by hand (`python show.py A`) |

## Results (2026-10-22 re-run, 10 runs each, every answer read and graded by a person)

| Setup | Result |
|---|---|
| A everything | correct 6 · wrong date math 2 ("window has passed/expired") · no clear yes/no 2 |
| B no tool definitions | invented a policy 2 (a "30-day window", "only unopened and undamaged") · asked the customer for info 8 |
| C no tool results (empty) | blamed the order ID 4 · asked for the category 6 |
| D no chat history | asked which order 10 |
| D0 control, history kept | wrong date math 10 ("expired as of today, 2026-10-19") |

## Notes

- The first English run (2026-10-20) used Korean-style items (frozen dumplings, sesame oil) and got A 10 · B 5/5 · C 5/5 · D 10 · control 2 correct / 8 wrong.
  It is kept as results_v1_korean_items.json. The English series switched to US grocery items (series_plan_en.md), so the experiment was re-run
  and the video uses this run. The same lessons hold; date math was even less reliable this time.
