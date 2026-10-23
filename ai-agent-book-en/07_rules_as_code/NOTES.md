# EN ep07 lab — rules as code (2026-10-23)

English re-run of the Korean ep042 lab, with US grocery items and an English HR database. All data fictional.

## Files

| File | What it does |
|---|---|
| lab.py | experiments A and B (usage in the docstring); hr.sqlite and golds_b.json are built before threads start |
| test_grade.py | server rule check gives the answer key for all 16 cases + B answer-line grader (24/24) |
| summarize.py | `python summarize.py a --case=YT-4010` / `b --q=B1` — per-case results with refunds, refusals, SQL, answers |

## Experiment A — correct out of 48 (16 requests × 3 runs)

| Model | Rules in prompt | Code check (checklist + server check) |
|---|---|---|
| gpt-4.1-nano | 7 · 36 wrong refunds out | 45 · 0 wrong refunds · 32 server refusals · 18 day miscounts + 1 'unopened' believed |
| gpt-4.1-mini | 39 · 8 wrong refunds out (day-8 pizza 3/3, opened cola 3/3, day-4 patties 2/3) | 48 · 0 wrong refunds · 11 refusals |

- nano's 3 misses with the code check: the server refused a wrong amount and the agent stopped to ask — no money out.
- Korean run: nano 8 → 31 (wrong refunds 37 → 0), mini 31 → 45 (15 → 0).

## Experiment B — correct out of 24 (8 questions × 3 runs), after re-running with clarified B6/B7

| Model | Read the tables | SQL | SQL + real values |
|---|---|---|---|
| gpt-4.1-nano | 2 | 6 | 8 |
| gpt-4.1-mini | 11 (12,862 tokens) | 10 (959) | 21 (1,246) |

- Plain SQL filtered `dept='production'` (real value 'Production Team') → 0 rows → "0 people", every time on B1.
- Average length of service (B2): many runs fetched hire dates with SQL and then did the date math themselves.
- Korean run: mini table 10 · SQL 23 (Korean team names were guessed right); English needed the real values.

## Mistake (said in the video)

First B run (results_b_v1.json): B6 'which employee' and B7 'who' — many runs found the right person (Wyatt Lewis / Liam Garcia)
but wrote the id (17) or the raise ($380) on the Answer line. Both questions now say "Answer with the employee's full name"; B was re-run.
