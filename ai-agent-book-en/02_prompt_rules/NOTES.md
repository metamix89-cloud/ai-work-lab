# EN ep02 lab — does the system prompt change the results? (2026-10-22, gpt-4.1-mini)

Yummy Tummy Foods (fictional) returns desk. 5 prompt versions × 10 customer messages × 4 runs = 200 real runs.
Graded from the tool-call log against an answer key written before the run (`grade()` in lab.py, self-tested by test_grade.py — 11/11).

## Files

| File | What it does |
|---|---|
| lab.py | the experiment (`python lab.py 4`) → results.json |
| test_grade.py | grader self-test, no API calls |
| fails.py | failures per version, with the agent's final reply |
| show.py | every run for one version and message (`python show.py B 1`) |

## Results (correct out of 40)

| Version | Correct | Failures |
|---|---|---|
| A baseline (procedure + specific rules + tool descriptions) | 38 | opened cola 12-pack refunded $6.80 (2) |
| B tone only ("returns fairy" voice + emoji) | 39 | frozen pizza on day 10 refunded (1) |
| C shuffled rules, no numbering | 37 | opened cola (2), pizza day 10 (1) |
| D no tool descriptions | 36 | gift basket: asked the customer to confirm phone digits they already gave, never called verify_customer, never escalated (4) |
| E vague rules ("appropriately · reasonably · carefully") | 17 | 23 mistakes: 8 high-value refunds without approval, 7 refunds past the window (4) or on the opened cola (3, invented partial $4.90), 8 wrong amounts (no return fee taken) |

- No version ever acted before verifying the customer (order violations 0) and no tool errors.
- The Korean run of the same design (ep035) got A 37 · B 40 · C 37 · D 35 · E 18 — the same story: tone barely matters, vague rules collapse.

## Notes

- Products are US grocery items so the English video feels natural (series list: items/ai-agent-book/series_plan_en.md).
  The first English run used Korean-style products (dumplings, sesame oil; A 34 · B 35 · C 38 · D 34 · E 16). It was replaced by this run
  before the video was made; the overall pattern was the same.
- An earlier 3-run start was stopped and restarted with 4 runs to match the Korean experiment.
- Customer messages use the clarified wording from the Korean run (its first run had two ambiguous messages).
