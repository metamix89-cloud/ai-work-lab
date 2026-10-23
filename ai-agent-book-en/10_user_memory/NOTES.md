# EN ep10 lab — user memory (2026-10-23, gpt-4.1-mini · text-embedding-3-small)

12 fictional contact records with ValueMart (June–October 2026) · 12 questions (3 levels × 4) × 4 conditions × 3 runs.

## Files

| File | What it does |
|---|---|
| lab.py | the experiment → results.json (emb_sessions.json built before threads) |
| test_grade.py | answer-check self-test (28/28) |
| regrade.py | re-grades saved answers with the current checks (keeps `ok_first`) |
| summarize.py | per-question results, failing answers, `--card` one memory card, `--sizes` card vs history length |

## Results (correct out of 36, after the L3-3 fix)

| Condition | Correct | Level 3 (flag first) | Tokens / question |
|---|---|---|---|
| M0 no memory | 0 | 0/12 | 131 |
| M1 full history | 35 | 11/12 | 1,072 |
| M2 search history (top 3) | 17 | 0/12 | 370 |
| M3 memory card | 33 | 11/12 | 1,124 (+ ~15,000 to build the card) |

- M2 retrieved the August "Mon/Wed/Fri" contact but not the September "back to Tue/Thu" one → confirmed a Monday frozen delivery (3/3);
  paid "on the 15th" (old terms); "Everything seems set for November 5 delivery" (certificate never retrieved).
- M3 card never recorded that pepperoni pizza is frozen → "Pepperoni Pizza is a pantry item … Columbus" (2/3).
- Card length 3,417–3,593 chars vs full history 3,704 chars.
- Korean run (ep045): all 32 · search 22 (flag first 0/12) · card 33.

## Mistake (said in the video)

L3-3 checked the date as 'October 31 | Oct 31 | 10/31' only. M3#2 answered "expires on 2026-10-31" and was marked wrong.
Added '10-31', added that answer to test_grade.py, re-graded with regrade.py (M3 32 → 33).
