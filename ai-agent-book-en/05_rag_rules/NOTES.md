# EN ep05 lab — handbook RAG (2026-10-22, gpt-4.1-mini · text-embedding-3-small)

Fictional Yummy Tummy Foods employee handbook (kb.md, 36 sections) · 20 questions of 5 types × 4 setups × 3 runs = 240 runs.
English re-run of the Korean ep040 lab; Korea-specific items were localized (job titles, expensive cities, USD, °F, food handler card).

## Files

| File | What it does |
|---|---|
| kb.md | the handbook (sections 35 and 36 are revisions of 4 and 14) |
| lab.py | the experiment → results.json (emb_cache.json is built once before threads start) |
| test_grade.py | answer-check self-test, right and wrong answers (45/45) |
| summarize.py | grounded counts by type, `--fails=R1` failing answers, `--q=Q12 --cond=R3` answers with search words |

## Results — grounded answers out of 60 (correct AND the needed sections were retrieved)

| Setup | Grounded | simple | code | two sections | revised | not in handbook | tokens / question |
|---|---|---|---|---|---|---|---|
| R0 no search | 8 (17 by answer check) | 0 | 0 | 0 | 0 | 8/9 | 95 |
| R1 plain RAG | 44 | 12 | 9 | 11 | 3 | 9 | 295 |
| R2 hybrid | 48 (50) | 12 | 12 | 9 | 6 | 9 | 295 |
| R3 agentic | 52 | 12 | 11 | 16 | 4 | 9 | 660 |

- R0 'correct' answers on simple/revised questions were guesses that happen to match common US practice (0°F freezers, 2 remote days);
  it also stated invented rules as the handbook ("at least 14 days in advance", "does not allow employees to bring dogs").
- R1 never retrieved section 12 for "HR-204" (semantic search missed the code); hybrid found it 3/3.
- R1 guessed grades ("A Director is grade A … $220"). R3 found the grade table with short search words.
- Revised questions: R3 searched "meal allowance business trip" and got the per diem section (3) instead of the revision (35) — 4/9.
- Korean run (ep040): R0 7 · R1 42 · R2 42 · R3 56; two sections 3 → 14. English: hybrid helped form codes; the agent was weaker on revisions.
