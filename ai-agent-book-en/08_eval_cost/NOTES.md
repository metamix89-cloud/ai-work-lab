# EN ep08 lab — evaluation and cost (2026-10-23, gpt-4.1-mini)

The agent under test is the EN ep07 returns agent (`../07_rules_as_code/lab.py`, imported unchanged).

## Files

| File | What it does |
|---|---|
| lab.py | `python lab.py pass` · `judge` (reads results_pass.json) · `cost` |
| summarize.py | `python summarize.py pass` per-case 5-run results · `judge` agreement and every wrong refund a judge passed |

## Results

**Pass (16 requests × 5 runs)**

| Condition | Average | Pass@5 | Pass^5 | Wrong refunds |
|---|---|---|---|---|
| rules in prompt | 76% | 13/16 | 12/16 | 14 |
| code check | 100% | 16/16 | 16/16 | 0 |

Prompt failures were systematic: YT-4002 (frozen pizza day 8) 0/5, YT-4005 (pantry day 14 wrongly declined) 0/5, YT-4007 (opened cola) 0/5, YT-4004 1/5.

**Judges (160 answers)**

| | J1 no criteria (4+ = pass) | J2 rubric + evidence |
|---|---|---|
| matched code grading | 67 | 160 |
| failed right answers | 91 (mostly score 3, "lacks empathy") | 0 |
| passed wrong answers | 2 (both wrong refunds: YT-4002, YT-4007) | 0 |

Korean run: J1 62/160 · J2 133/160 with 13 wrong refunds passed (day counting). The English rubric judge had no misses — say both in the video.

**Cost (8-turn task, average of 3)**

| Setup | Input | Cached | Cost | Saved |
|---|---|---|---|---|
| changing prefix, no compression | 65,266 | 0 | $0.0271 | — |
| stable prefix, no compression | 63,300 | 53,760 | $0.0102 | 62% |
| changing prefix, compressed | 38,647 | 0 | $0.0167 | 38% |
| stable prefix, compressed | 36,788 | 26,752 | $0.0078 | 71% |
