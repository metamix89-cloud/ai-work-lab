# AI Work Lab — experiment code behind the videos

**Languages:** [English](README.md) · [한국어](README.ko.md)

Every number shown in the videos comes from these scripts. All companies, customers and data are fictional.
Each lab folder has a `NOTES.md` (results, mistakes we made) and usually `test_grade.py` (grader self-test).
Put your `OPENAI_API_KEY` in a `.env` file (never commit it) and run `python lab.py` as described in each file's docstring.
Phone numbers in the fictional test data are replaced with `010-0000-xxxx` placeholders in this public copy (consistently across code and results).
Code in this repository is MIT licensed (see `LICENSE`); the courses it retells keep their own licenses, credited under each series.

## AI Agents in Depth (11 episodes)

Based on bojieli/ai-agent-book — Apache-2.0 — retold with new examples; not an official course by the authors.

| Episode | Video | Folder | What it measures |
|---|---|---|---|
| 01_agent_basics | (not yet published) | `ai-agent-book-en/01_agent_basics` | EN ep01 lab — Yummy Tummy Foods (fictional) customer-support agent. Core loop written by hand, no framework. |
| 02_prompt_rules | (not yet published) | `ai-agent-book-en/02_prompt_rules` | EN ep02 lab — do the system prompt and tool descriptions change performance? (book ch.2 experiment 2-4 style) |
| 03_agent_skills | (not yet published) | `ai-agent-book-en/03_agent_skills` | EN ep03 lab — open skills only when needed (book ch.2 experiment 2-6 style), 9 Yummy Tummy Foods (fictional) work skills. |
| 04_context_compress | (not yet published) | `ai-agent-book-en/04_context_compress` | EN ep04 lab — when the conversation gets long: comparing context-compression strategies (book ch.2 experiment 2-10 style). |
| 05_rag_rules | (not yet published) | `ai-agent-book-en/05_rag_rules` | EN ep05 lab — asking the employee handbook: no retrieval · plain RAG · hybrid search · agentic RAG (book ch.3 experiments 3-6 · 3-8 style). |
| 06_tools_safety | (not yet published) | `ai-agent-book-en/06_tools_safety` | EN ep06 lab — 100 tools: load all · pick ahead · find when needed (book ch.4 experiment 4-1) + an approval reviewer before irreversible actions. |
| 07_rules_as_code | (not yet published) | `ai-agent-book-en/07_rules_as_code` | EN ep07 lab — rules as code (book ch.5 experiments 5-5 · 5-13 style). English re-run of the Korean ep042 lab. All data is fictional. |
| 08_eval_cost | (not yet published) | `ai-agent-book-en/08_eval_cost` | EN ep08 lab — how do you know it works: evaluation and cost (book ch.7 Pass@k · Pass^k · LLM-as-a-Judge · experiment 7-10 cost breakdown). |
| 09_multi_agent | (not yet published) | `ai-agent-book-en/09_multi_agent` | EN ep09 lab — when several agents split the work (book ch.10 'when multi-agent really helps', table 10-1 · failure mode 'error cascades'). |
| 10_user_memory | (not yet published) | `ai-agent-book-en/10_user_memory` | EN ep10 lab — bonus 1: an agent that remembers you, user memory (book ch.3 'user memory · three-level evaluation · memory formats' · experiments 3-1 · 3-2). |
| 11_computer_use | (not yet published) | `ai-agent-book-en/11_computer_use` | EN ep11 lab — bonus 2: an agent that operates a screen (book ch.6 'computer use · action space · visual grounding' · experiment 6-9). |

## Before You Hand Work to AI — Season 2 (12 episodes)

Based on rohitg00/ai-engineering-from-scratch — MIT — retold with new examples; not an official course by the authors.

| Episode | Video | Folder | What it measures |
|---|---|---|---|
| 01_outcome_first | (not yet published) | `ai-engineering-from-scratch-en/01_outcome_first` | EN es01 lab — Outcomes before output (source: AI Engineering from Scratch, Phase 14 lesson 47, the 6-box outcome frame). |
| 02_real_workflow | (not yet published) | `ai-engineering-from-scratch-en/02_real_workflow` | EN es02 lab — Discover the workflow people actually perform (source: AI Engineering from Scratch, Phase 14 lesson 48). |
| 03_riskiest_first | (not yet published) | `ai-engineering-from-scratch-en/03_riskiest_first` | EN es03 lab — Map assumptions and resolve the riskiest one first (source: AI Engineering from Scratch, Phase 14 lesson 49). |
| 04_smallest_slice | (not yet published) | `ai-engineering-from-scratch-en/04_smallest_slice` | EN es04 lab — Choose the smallest slice that can change the decision (source: AI Engineering from Scratch, Phase 14 lesson 50). |
| 05_judgment_spec | (not yet published) | `ai-engineering-from-scratch-en/05_judgment_spec` | EN es05 lab — Write specifications that preserve judgment (source: AI Engineering from Scratch, Phase 14 lesson 51). |
| 06_success_metrics | (not yet published) | `ai-engineering-from-scratch-en/06_success_metrics` | EN es06 lab — Design success metrics before the result exists (source: AI Engineering from Scratch, Phase 14 lesson 52). |
| 07_stage_drift | (not yet published) | `ai-engineering-from-scratch-en/07_stage_drift` | EN es07 lab — Prototype, pilot, production (source: AI Engineering from Scratch, Phase 14 lesson 53 'Choose Prototype, Pilot, or Production Deliberately'). |
| 08_task_frame | (not yet published) | `ai-engineering-from-scratch-en/08_task_frame` | EN es08 lab — Frame the task before the agent writes code (source: AI Engineering from Scratch, Phase 14 lesson 43). |
| 09_evidence_plan | (not yet published) | `ai-engineering-from-scratch-en/09_evidence_plan` | EN es09 lab — Build an evidence-backed execution plan (source: AI Engineering from Scratch, Phase 14 lesson 44). |
| 10_isolate_work | (not yet published) | `ai-engineering-from-scratch-en/10_isolate_work` | EN es10 lab — Delegate agent work with isolation and merge contracts (source: AI Engineering from Scratch, Phase 14 lesson 45). |
| 11_feedback_system | (not yet published) | `ai-engineering-from-scratch-en/11_feedback_system` | EN es11 lab — Turn every agent correction into a system improvement (source: AI Engineering from Scratch, Phase 14 lesson 46). |
| 12_feedback_ratchet | (not yet published) | `ai-engineering-from-scratch-en/12_feedback_ratchet` | EN es12 lab — Build a feedback ratchet with ownership and retirement (source: AI Engineering from Scratch, Phase 14 lesson 54). |
