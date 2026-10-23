# EN ep03 lab — open skills only when needed (2026-10-22, gpt-4.1-mini)

9 Yummy Tummy Foods (fictional) work skills, 10 requests. Book ch.2 experiment 2-6 (progressive disclosure), re-done in English.

## Files

| File | What it does |
|---|---|
| make_skills.py | writes skills/ (9 SKILL.md + reference files + bundled make_ppt.py) — run once |
| lab.py | the experiment → results*.json (usage in the docstring) |
| test_grade.py | grader self-test, no API calls (26/26) |
| regrade.py | re-grades saved answers with the current grader (keeps the first grade in `ok_first`) |
| summarize.py | correct per setup × task, tokens, failures, `--answers=T2` for full replies |

## Results (correct out of 50, after the T6 grader fix)

| Setup | Correct | Tokens / request | First call | Excel question alone |
|---|---|---|---|---|
| N no skills | 10 | 101 | 101 | 57 |
| A everything in | 42 | 5,111 | 2,874 | 2,830 |
| B on demand | 44 | 1,381 | 582 | 538 |
| D vague catalog | 41 | 1,055 | 373 | 329 |

- Return decisions (T2 + T10): B 10/10 · A 2/10 (first-line format broken 6, one self-contradiction, one unbracketed) · D 3/10 (never opened the skill for the spoiled BBQ sauce, 0/5).
- Stock alert (T6): A 5 · B 1 (3 never opened the skill, 1 called 140 < 150 OK) · D 4 (1 called everything OK) → 10/15.
- Expense (T7): 14/15. Requests needing no skill (T8, T9): no skill opened, 30/30.

## PPT request alone (T1)

| Run | Result |
|---|---|
| B on demand, 10 runs (results_t1.json) | 7/10 — 3 skipped the manual, sent their own JSON, got 0 slides, still said "created" |
| B2 one line in the run_script description, 5 runs | 5/5 (the Korean run of the same fix: 0/5) |
| B3 guard in code, 10 runs | 9/10 — 3 runs refused first, then read and succeeded; 1 read the manual but sent raw numbers → 0 slides, still listed 5 slides |

## Mistakes (shown in the video)

1. **T6 grader bug:** it graded the first line that named each item. Most models write the calculation first and the 🔴/🟢 alert lines after,
   so 10 correct answers were marked wrong (A 5, B 1, D 4). Fixed to read the line with the marker; test_grade.py got a case for it;
   results.json re-graded with regrade.py. The Korean ep038 results were re-checked with 03_agent_skills/t6_recheck.py — no difference.
2. Products were first written as Korean-style items (dumplings, sesame oil); replaced with US items (pizza, cola, burger patties) and re-run
   before the video was made.
