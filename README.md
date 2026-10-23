# AI Work Lab — experiment code behind the videos

**Languages:** [English](README.md) · [한국어](README.ko.md)

Every number shown in the videos comes from these scripts. All companies, customers and data are fictional.
Each lab folder has a `NOTES.md` (results, mistakes we made) and usually `test_grade.py` (grader self-test).
Put your `OPENAI_API_KEY` in a `.env` file (never commit it) and run `python lab.py` as described in each file's docstring.
Phone numbers in the fictional test data are replaced with `010-0000-xxxx` placeholders in this public copy (consistently across code and results).
Code in this repository is MIT licensed (see `LICENSE`); the courses it retells keep their own licenses, credited under each series.
Each entry below is what we tried and what came out, with the video that walks through it.

## AI Agents in Depth (11 episodes)

Based on bojieli/ai-agent-book — Apache-2.0 — retold with new examples; not an official course by the authors.

### 01 · What makes an agent work

We built a returns-desk agent as a 30-line loop and pulled the context parts out one at a time, 10 runs per setup. Without tool definitions, two runs invented a 30-day return policy. Without tool results, every run pushed the problem back to the customer. Even with the delivery date and the policy in front of it, 12 of 20 runs got simple date math wrong, which is where the harness idea starts.

▶ Video coming soon · [📁 Code](ai-agent-book-en/01_agent_basics)

### 02 · Tone vs. rules in the system prompt

Same model, same tools, only the system prompt changed, 200 runs. A bubbly 'returns fairy' tone barely mattered (39/40 vs 38/40). Vague rules like 'appropriately' and 'reasonably' dropped it to 17/40, and every one of the 23 mistakes sent money out the door. Even specific rules slipped on an opened cola, which is why the rules later move into code.

▶ Video coming soon · [📁 Code](ai-agent-book-en/02_prompt_rules)

### 03 · Skills opened only when needed

Nine company manuals as Agent Skills, ten requests, five runs each. Opening a skill only when needed scored 44/50 with about a quarter of the tokens of loading everything (42/50). With vague one-line descriptions the agent never opened the returns skill for spoiled BBQ sauce. On the PPT request it sometimes skipped the manual, produced an empty file and still said 'created', so we enforced the order in code.

▶ Video coming soon · [📁 Code](ai-agent-book-en/03_agent_skills)

### 04 · Seven ways to compress a long conversation

A 20-turn day with a grocery buyer where catalogs and stock sheets pile up, and six facts settled along the way must reach the final order confirmation. No compression overflowed the window. Dropping old turns lost the payment terms agreed in chat. Summarizing long tool results kept all 30 facts with a quarter of the tokens, while progress notes missed a date and even wrote down wrong ones.

▶ Video coming soon · [📁 Code](ai-agent-book-en/04_context_compress)

### 05 · Search once vs. an agent that searches

A fictional 36-section employee handbook, 20 questions, 240 runs. With no search the model invented rules and presented them as ours. Searching once got 44/60 grounded answers, hybrid search 48, letting the agent search 52. The gap came from questions that need two sections, like a job title plus the grade table, and revisions kept apart from the old section were missed even by the agent.

▶ Video coming soon · [📁 Code](ai-agent-book-en/05_rag_rules)

### 06 · 100 tools and a reviewer for what can't be undone

An agent with 100 internal tools: loading them all scored 36/36, picking ahead 33, finding tools when needed 28 with a seventh of the tokens. When the search missed, the agent improvised with tools that have side effects. With safety rules only in the prompt it deleted a customer's entire order history 4 times out of 5. An approval reviewer stopped every risky request and blocked no normal work.

▶ Video coming soon · [📁 Code](ai-agent-book-en/06_tools_safety)

### 07 · Wrong refunds 36 to 0

Sixteen return requests with the rules only in the prompt: the small model sent out 36 wrong refunds, mini 8. A code check inside the refund tool, working from database facts instead of the model's, brought both to zero. For HR questions, letting SQL do the math scored 21/24, but only once the tool showed real values; plain SQL filtered on 'production' and answered 'zero people'.

▶ Video coming soon · [📁 Code](ai-agent-book-en/07_rules_as_code)

### 08 · Pass^k, AI judges and cost

The returns agent averaged 76%, yet three requests failed every single time, so we measured right-once (Pass@5) against right-every-time (Pass^5). An AI judge with no criteria failed 91 correct answers and passed two wrong refunds; with a rubric and evidence it matched all 160. On cost, keeping the start of the prompt stable cut 62%, compression 38%, both together 71%.

▶ Video coming soon · [📁 Code](ai-agent-book-en/08_eval_cost)

### 09 · Solo vs. chain vs. reviewers

Twelve quality claims, 144 runs. One agent refunded an $89 recall claim it should have escalated, every time. A chain of intake, quality and billing agents got all 36 because the quality agent wrote the exact amount into its handoff note. Reviewers after the fact made it worse: the money was already out. In our Korean run the chain lost an amount in a note and did worse, so what matters is the note, not the number of agents.

▶ Video coming soon · [📁 Code](ai-agent-book-en/09_multi_agent)

### 10 · History vs. search vs. a memory card

Twelve conversations with a grocery account over four months: delivery days changed and changed back, the buyer and the payment day changed, a certificate expires. Full history scored 35/36, a rewritten memory card 33, searching the history 17. On flagging things first, search got 0 of 12 and confirmed a Monday delivery from a stale fact. The card's cost and where it slipped are in the notes.

▶ Video coming soon · [📁 Code](ai-agent-book-en/10_user_memory)

### 11 · Element index vs. screenshot vs. code

A fictional back-office screen, five requests, 50 runs. Reading the page structure with numbered elements: 15/15 with about 4,000 tokens. Number marks drawn on a screenshot: 13/15 at 13x the tokens. Clicking by screenshot coordinates: 1/15, it kept clicking a few pixels below each field. Freezing the working steps in code ran all five in about 3 seconds with no tokens.

▶ Video coming soon · [📁 Code](ai-agent-book-en/11_computer_use)

## Before You Hand Work to AI — Season 2 (12 episodes)

Based on rohitg00/ai-engineering-from-scratch — MIT — retold with new examples; not an official course by the authors.

### 01 · Outcomes before output

We took a 26-item inventory sheet and asked for 'a weekly inventory report' six different ways, 10 runs each. Output-only requests copied the unit-cost column that must not reach the meeting screen in up to 9 of 10 runs. The 6-box outcome frame brought cost leaks to 0 and cut the length by two thirds. But finding the six items that run out before their next delivery stayed at 1 in 10 until we wrote down how to check and moved the math into code: then 10 of 10.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/01_outcome_first)

### 02 · The manual vs. the real work

A 4-step returns manual, a team lead's interview, and an AI asked to design the automation, 40 runs. From the manual and the interview it found none of the 7 pieces of hidden work and took the interview's '5 minutes each' as fact every time. With the real processing logs, chat and personal notes it found 4.8 of 7, but none noticed the two reps work in different orders. With evidence and its strength written for every step: 6.8 of 7, and all 10 caught the two orders.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/02_real_workflow)

### 03 · Set the bar before the result

Thirty plans for the first two weeks of a return-photo AI project. Asked for a plan right away, none set a numeric pass bar before the test; with the course's method all 10 did (85 to 90%) and wrote what to do on failure. Then every plan got the same result, 82% agreement with 18 wrong refunds: 30 of 30 chose 'reduce the scope and keep going', and not one mentioned its own bar. Set the bar before the result, and have a person apply it.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/03_riskiest_first)

### 04 · Small, but keep the risk inside

Six candidate first-pilot scopes, from a UI mock-up to automatic refunds. Asked to 'pick the smallest', the AI chose the easy box-damage-only slice 10 times out of 10, even though most wrong refunds come from frozen spoilage. A team lead pushing for next week's meeting changed nothing. Asked to decide what must be proven first and drop anything that doesn't cover it, all 10 picked the slice with the risk inside and wrote a stop rule.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/04_smallest_slice)

### 05 · Fixed, bounded, delegated

A support agent with 5 fake tools, 12 requests, 3 specs, 108 runs graded from the tool-call log. 'Be friendly, use your judgment' refunded an $89 steak box without approval and gave a stranger a customer's phone number. A step-by-step script did about the same, and on a hair in the salsa and a child's hives it sent the scripted apology and a $3 coupon 6 of 6, never escalating. The course's spec got 33 of 36 with zero rule violations and $0 in wrong refunds, while still choosing coupon amounts and wording itself.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/05_judgment_spec)

### 06 · Guardrails at zero

A 2-week 'AI first response' pilot with good and bad mixed in: first response from 4 hours to 3 minutes, but re-contacts up, 2 out-of-policy refunds and an allergy request never handed to a person. Judging from the results, 10 of 10 said expand while fixing. Letting the AI write its own measurement plan first: still 10 of 10, because its guardrails were rates that 2 in 1,240 passes. A plan written by a person, guardrails at 0 and 'any break means hold', held the expansion 10 of 10.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/06_success_metrics)

### 07 · Rules in words don't stop stage drift

A prototype quote builder and an internal assistant asked to share it with 40 reps, connect the real price DB, turn on customer emails and switch it to production. A plain assistant did all four risky things 5 of 5. Given the prototype / pilot / production rules in words, it still did all four and attached a 'prototype' tag plus a list of control names with nobody behind them. When the tools themselves refuse, risky executions dropped to 0 and the same assistant explained exactly what was missing.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/07_stage_drift)

### 08 · Recon before the frame

A file agent in a Purchasing folder asked to 'apply the supplier's price increase', 40 runs. The vague request never opened the README and overwrote the old price row 10 of 10. Telling the agent to write a task frame first filled in the form but still skipped the README and three times declared a 30-day notice met when it was 17 days. Add the course's recon step, find the constraints first, and it read the rules 9 of 10 and once stopped to ask about the contract clause.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/08_task_frame)

### 09 · Dependencies over format

Thirty plans for a returns-window change, every sequence table read by hand. The one question: is the customer SMS, which can't be recalled, placed after the system change it depends on? A plain plan got that right 6 of 10. The course's format with evidence and dependencies on every item got longer plans and only 1 of 10 kept the order, because the SMS hung on the notice-template line. A separate check for irreversible steps brought it back to 4.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/09_evidence_plan)

### 10 · Split the files, not the promise

Three agents (prices, allergens, shipping) editing one product sheet at the same time, 40 runs. On a shared file the last save erased the other two agents' edits every time, 0 of 10, and all three reported 'done'. Telling each agent 'your section only' in words changed nothing. Giving each agent its own file, with the tool refusing writes anywhere else, and stitching in code: 10 of 10 and the fastest. One at a time also got 10 of 10 but took three times as long.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/10_isolate_work)

### 11 · The cause, not the symptom

A quote-writing AI corrected three times by the team lead, then 10 new quotes under four conditions, 80 quotes in all. With the lead's words kept as a note, 0 of 20 were perfect: October quotes got the November price and 'don't write plus tax' removed tax from the quote entirely. With the causes written as rules, 18 of 20. A code checker that names only the violated rule took it to 20 of 20.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/11_feedback_system)

### 12 · One owner, one retire condition

Week 4 of the 'AI first response' pilot: 12 signals and 20 improvement plans. A plain plan grouped the same-cause signals 8 of 10, but 0 of 10 retired the control nobody has violated in 12 weeks that costs agents 40 minutes a day; every plan kept it and added automation on top. The course's ratchet (group by cause, earliest layer, one owner, how to verify, review date, retire condition) retired it 9 of 10 with the evidence. Season finale, with the twelve lessons on one page.

▶ Video coming soon · [📁 Code](ai-engineering-from-scratch-en/12_feedback_ratchet)
