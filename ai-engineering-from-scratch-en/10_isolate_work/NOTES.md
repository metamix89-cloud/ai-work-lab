# EN es10 lab notes (2026-10-23, gpt-4.1-mini, 4 conditions x 10 runs, 3 agents per run)

English re-run of the Korean 10_isolate_work: three agents (prices · allergens · shipping) edit the Yummy Tummy Foods (fictional) trade-customer product sheet. 3 sections, 7 edits (2 · 3 · 2), 3 'keep as is' lines.
Tools: read_file · write_file (saves the whole file). One tool call is atomic under a lock - but 'read -> think -> save the whole file' can still interleave.

## Results (results.json, side_damage.py)

| Condition | perfect | edits survived (avg /7) | collateral damage | time |
|---|---|---|---|---|
| A one shared file, all at once | 0/10 | 2.1 | 0 | 3.9 s |
| C ownership in words ("your section only") | 0/10 | 2.3 | 0 | 3.7 s |
| B split files (write only your own file; code stitches) | **10/10** | 7.0 | 0 | 3.1 s |
| S one at a time, same file | 10/10 | 7.0 | 0 | 10.5 s |

- **A0 timeline:** 1.5 s prices and shipping read · 1.6 s allergens read · 2.9 s prices saved · 3.1 s shipping saved · 3.1 s allergens saved. The final document has only the allergen edits; the last save erased the other two. All three agents reported "done".
- **A1:** the same race, this time the pricing agent saved last - only the price edits survived.
- **C0:** every agent edited only its own section, as told - and saved 'original + my section' as the whole file. Last save wins (shipping). Ownership in words held; it did not prevent the overwrite.
- **B:** no agent ever tried to write another file (refused 0); 7/7 edits and 3/3 keep lines survived in all 10 runs. Fastest too (3.1 s) - three agents in parallel, no contention.
- **S:** correct 10/10 but 3x slower (10.5 s). Korean run: S 9/10 with 4 runs of collateral damage from re-writing someone else's section (a dropped middle dot, '떡볶이 소품'); here 0 - the English rewrite kept the other sections verbatim every time.
- Same lesson as episode 6 of season 1 (en06): a shared file written by parallel threads.

## Grading

- The 7 edits and 3 keep lines by regex (test_grade: answer 7/3, original 0/3, 'last save only' 3). Collateral damage = lines in neither the original nor the answer (side_damage.py).
