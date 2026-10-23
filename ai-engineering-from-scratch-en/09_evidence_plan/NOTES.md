# EN es09 lab notes (2026-10-23, gpt-4.1-mini, 3 conditions x 10 plans)

English re-run of the Korean 09_evidence_plan: the frozen-returns window at Yummy Tummy Foods (fictional) goes from 7 to 14 days; 6 background facts; the AI writes the execution plan.
- Facts: Legal finalizes the wording (10/28) · the intake screen blocks after 7 days, no Friday deployments · a notice template exists · SMS only to 12,000 opted-in customers and it cannot be recalled · the manual and chatbot say '7 days', training after the manual.
- Every plan ends with a sequence table (No. | task | must finish first).

## Conditions

- A: plan only
- B: the lesson's way - per item number · change · evidence · what must finish first · evidence of done; order by dependency; same-wave work; irreversible after its uncertainties
- C: B + a check after planning: for every irreversible task, "what does the other side do right after, and what must already be finished for that to succeed" -> add as a dependency

## Result - is the customer SMS (irreversible) placed after the system change? (all 30 tables read by a person, manual.py)

| Condition | SMS after the system change (by hand) | (code) | items avg | waves avg | template reused | opt-in only | no Friday deploy |
|---|---|---|---|---|---|---|---|
| A plan only | 6/10 | 5 | 6.7 | 3.9 | 10 | 10 | 10 |
| B the lesson's way | **1/10** | 1 | 8.4 | 4.0 | 10 | 10 | 10 |
| C B + irreversible check | 4/10 | 4 | 7.9 | 4.1 | 10 | 10 | 10 |

- Hand judgments: A yes = 0, 1, 2, 3, 8, 9 (A8 by dates: deploy 10/31, SMS from 11/3) · B yes = 2 · C yes = 0, 1, 3, 8.
- **B's shape:** the SMS send hangs only on the notice/template line (e.g. B6: SMS 7 <- template 6 <- Legal 1), never on the intake-screen change. B8 even puts "Deploy all changes live" as the last item, after the SMS was sent. B0 and B9 use a 'Management enforces the effective date' row that depends on both - but the SMS itself does not.
- **A:** the plain plans more often tied the send to the deploy directly (A0: SMS 5 <- [3, 4] where 4 is the deploy; A9: SMS 5 <- [2, 3, 4]).
- **C:** the irreversible check brought it back to 4 (C0, C1, C3, C8 all have SMS <- [template, system]). C7 'sends' at item 6 (template only) and then 'launches the SMS' again at item 7 (after the deploy) - counted as not after.
- **Evidence use:** template, opt-in and Friday all 30/30 - facts given as a list are reflected; the hard part is the link between facts (SMS <-> system), which is written nowhere.
- Same picture as the Korean run (7 -> 3 -> 6): the format increased the item count and did not improve the dependency that matters; the explicit irreversible check helped only partly.

## Grading

- Code grouping of tasks into kinds (sms · prep · legal · system ...) and dependency following; 'prepare and send' on one line, or 'send' + 'launch' twice, confused it, so all 30 tables were read and judged by hand (manual.py). Code and hand differ by 1 (A8).
