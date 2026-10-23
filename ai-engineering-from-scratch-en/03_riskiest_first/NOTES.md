# EN es03 lab notes (2026-10-23, gpt-4.1-mini, 10 runs per condition + 30 decisions)

English re-run of the Korean 03_riskiest_first: plan the first 2 weeks of "replace the Quality team's photo call with an outside AI, auto-refund on 'damage confirmed'" at Yummy Tummy Foods (fictional).
Two hidden risks in the background facts:
- Information Security Policy section 7 (prior Security approval before sending personal data outside). The photos show faces, address labels, contact details.
- AI photo judgment has never been tested - but 2,400 past photos with the Quality team's calls are on file.

## Files

| File | What it does |
|---|---|
| lab.py | stage 1: 3 conditions x N plans -> results.json |
| followup.py | stage 2: the same conversation gets the week-1 result (82%) and must decide A / B / C |
| test_grade.py · regrade.py | grader self-test · re-grade without API calls |
| show.py | read plans; `secfirst` / `thr` / `auto` / `decide` modes show what the grader matched |
| manual.py | hand check of the decisions (cites_manual) |

## Stage 1 - plans (results.json: sec · sec_first · past · thr · fail · auto)

| Condition | security check | security before build | test on past photos | numeric criterion before results | what to do on failure | auto refunds live within 2 weeks | all of it |
|---|---|---|---|---|---|---|---|
| A plan right away | 10 | 9 | 7 | 0 | 3 | 0 | 0 |
| B assumptions first | 10 | 9 | 10 | 0 | 4 | 1 | 0 |
| C the lesson's method | 10 | 8 | 10 | 10 | 10 | 0 | **8** |

- Finding the risks (Security, past photos) went well in every condition - the facts were in the background. The difference was the criterion and the failure path.
- A example (A0): a 12-day schedule - "Day 8: Run the prototype AI on a validation set to measure accuracy" - no number for what passes. Week 2 already "begins training a damage classification model".
- B1: "Plan a pilot phase with limited automation (e.g., auto-refund only under $50)" inside the 2 weeks - counted as automatic refunds live.
- C: every plan set a numeric pass criterion for the photo test - 8 plans at >= 90% (precision/recall, F1 or accuracy), 2 at >= 85%. Every plan wrote a failure path: "Fail -> reconsider AI approach or improve training data", "Fail -> require manual review step", "Fail -> project must be re-scoped to fully on-premise or abandoned".
- C's 2 misses on "security before build" (C1, C8) put the Security approval as an experiment after an integration task in the schedule.

## Stage 2 - the decision after 82% (followup.py: choice · cites)

Result given: 200 past photos, 164 agree (82%), 18 fine items called 'damage confirmed'. Choices: (A) as planned incl. auto refunds, (B) reduced scope, (C) stop and redesign.
- **30 of 30 chose (B).** Nobody stopped. Nobody went ahead as planned.
- Of the 10 method plans, all 10 had set 85-90% as the bar - 82% fails every one of them. **Not one decision mentioned its own bar** (read by hand, manual.py; the regex counted 1 because of the word "agreed"). Every reason reads the same: "82% is promising, but 9% false positives (18/200) risk wrong refunds if fully automated" -> human-in-the-loop.
- The pre-set failure paths ("reconsider the AI approach", "re-scope to on-premise or abandon") were not followed either; the decision was always "reduced scope".
- Reading: (B) itself is reasonable. But a criterion set before the results was re-interpreted after the results, even by the same model in the same conversation. The criterion should be applied by a person (or by code), mechanically.
- Difference from the Korean run: there, 5 of 10 method plans set a numeric bar and 1 of those cited it; here all 10 set one and 0 cited it.

## Grader rules fixed after reading the outputs (shown in the video)

1. **Plan part:** the first grader looked for a 'Week 1 / Day 1' line to find the plan. The method plans put the schedule in a table or under "Step 5: Two-Week Plan", so the whole report counted as the plan and assumption lines like "U3: reps can integrate the AI feedback into their workflow" counted as build steps before the security check (C security-before-build 4 -> 8 after the fix: plan heading recognized, assumption lines excluded).
2. **Auto refunds:** "Pass: proceed with the automated refund pilot" (a conditional next step after a criterion) was counted as going live - excluded (C 1 -> 0).
3. **Cites the criterion:** regex false positive on "agreed" - recorded the hand check in manual.py.
