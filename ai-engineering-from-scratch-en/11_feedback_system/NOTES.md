# EN es11 lab notes (2026-10-23, gpt-4.1-mini, 10 quotes x 2 runs x 4 conditions = 80)

English re-run of the Korean 11_feedback_system: a quote-writing AI at Yummy Tummy Foods (fictional). Last session's 3 corrections from the team lead:
"pizza sauce is $79.30, not $73.40" · "don't write 'plus tax'" · "you left out the validity period". How they are kept decides whether they recur.
- 10 new quotes; the 3 dated in October (T3 · T5 · T8) must use the OLD price. A 2027 price row is in the list too.
- Grading (code): unit prices · '(tax included)' wording · validity = quote date + 14 days.

## Results (results.json)

| Condition | perfect | prices right | October quotes (old price) | '(tax included)' | validity date right |
|---|---|---|---|---|---|
| A no record | 0/20 | 27/34 | 8/10 | 0 (no tax wording at all) | 0 (no validity line) |
| B symptom note (the lead's words) | 0/20 | 26/34 | 6/10 | 1 | 0 ("valid for 30 days") |
| C cause rules | 18/20 | 34/34 | 10/10 | 20 | 18 |
| D cause rules + checker | 18/20 (17 before the checker) | 34/34 | 10/10 | 20 | 18 |

- **A:** writes a plain table and a total; no tax wording, no validity line at all. Prices: 7 wrong of 34, 2 of them October quotes using the November price.
- **B "pizza sauce is $79.30":** applied to October quotes too - T3 (10/25) and T5 (10/30) got $79.30 in 1 of 2 runs each (October right 6/10 vs A's 8/10: the note made it worse). "Don't write 'plus tax'" -> the tax is simply never mentioned (1/20 wrote "prices are tax included"). "Add the validity period" -> "This quote is valid for 30 days from the date above" in all 20 - a period, not the 14-day rule, and no date.
- **C:** all prices right incl. the October ones; '(tax included)' 20/20; validity 18/20. The 2 misses are the same quote (T7, dated 2026-11-20) in both runs: "Valid until: 2027-12-04" - the right day and month, the wrong year (date math slip).
- **D:** the checker ("rule violations: validity. Re-check the rules and rewrite") fixed 1 of the 3 first-pass failures, but on T7 the AI rewrote "Valid until: 2027-12-04" again, twice. A checker that names the rule can't fix a wrong year the model believes in - the Korean run's checker brought 18 -> 20; here 17 -> 18.

## Difference from the Korean run

- Korean: A 25/34 prices · 5/10 October · tax wording 19 (Korean quotes mention VAT by habit) · validity 0; B 28/34 · 4/10 · 0 · 2; C 19/20; D 20/20.
- English: the no-record agent never mentions tax at all (0 vs 19), and the cause-rule agent's one remaining error is a year typo the checker couldn't dislodge.
