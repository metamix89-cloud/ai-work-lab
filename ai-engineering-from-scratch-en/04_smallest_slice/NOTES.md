# EN es04 lab notes (2026-10-23, gpt-4.1-mini, 10 runs per condition)

English re-run of the Korean 04_smallest_slice: picking the first pilot scope for the return-photo AI project (episode 3).
- Background: box damage 35% (easy, rarely disputed) · frozen/refrigerated spoilage 40% (most disputes and wrong refunds; 15 of last week's 18 misjudged items). Still unknown: accuracy per type, and whether reps' handling time drops.
- What must be proven: accuracy on real photos of every type (esp. spoilage) · reps' handling time · reversible.

## Choosing among 6 candidates (S1 UI-only · S2 box damage only · S3 right · S4 auto refunds · S5 platform · S6 demo)

| Condition | choice |
|---|---|
| A "pick the smallest" | S2 10/10 |
| B + team-lead pressure ("fast and cheap, next week's management meeting") | S2 9/10 · S6 demo 1/10 |
| C the lesson's way (must prove -> drop what doesn't cover it -> compare -> stop rule) | S3 10/10 |

- A example: "S2 ... focuses on shelf-stable box damage, which is easy to judge and rarely disputed, minimizing risk" - exactly why it proves nothing.
- B example: "This will give management a clear, fast win with minimal effort before the meeting." B5 picked the demo video: "produces a tangible demo for management ... a fast win".
- C example: "S2 is too narrow (only box damage), missing spoilage accuracy and time impact. S1 and S6 don't test accuracy or time reduction in real use; S4 risks premature automation" and "If S3 fails (low accuracy or no time gain), stop and reconsider".

## Proposing a scope with no candidates (P plain · Q the lesson's way)

| Condition | covers frozen / spoilage | past data | reps use it + time recorded | automatic refunds | stop rule |
|---|---|---|---|---|---|
| P plain proposal | 10 (hand-checked) | 10 | 7 | 0 | **0** |
| Q the lesson's way | 10 (hand-checked; code 9) | 10 | 10 | 0 | **10** |

- **Different from the Korean run:** there, 5 of 10 plain proposals picked box damage only. Here all 10 plain proposals went straight for frozen/refrigerated spoilage ("40% of returns and most disputes"). The easy-case trap showed up only when a "smallest" candidate was on the table (A, B). But the plain proposals still had no stop rule (0/10) and 3 of 10 never measured the reps' time.
- Q: "If AI accuracy < 80% or handling time reduction < 10% after the 2-week pilot, stop AI-assisted calls", "If AI accuracy on frozen/refrigerated spoilage falls below 75% ... stop the pilot immediately". Q0 also wrote why the smaller scopes were rejected: "Testing only box damage (35%) is low risk and easy but doesn't cover the biggest uncertainty".

## Grading

- Choices (A-C): the first line 'Choice: S<n>'.
- Scope classification (P, Q) by code looked only at the scope part (up to the 'who' item). It mis-read Q0: the negation "Testing ONLY BOX DAMAGE ... doesn't cover" matched the 'box damage only' rule. All 20 scope parts were read by a person (show.py P scope / Q scope) and stored as frozen_manual (manual.py): P 10, Q 10.
- The Korean grader had the same kind of problem the other way round ("later expand to frozen" counted as covered); both runs ended up hand-classified.
