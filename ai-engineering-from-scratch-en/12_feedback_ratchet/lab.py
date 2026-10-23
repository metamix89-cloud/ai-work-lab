# -*- coding: utf-8 -*-
"""EN es12 lab — Build a feedback ratchet with ownership and retirement (source: AI Engineering from Scratch, Phase 14 lesson 54).
English re-run of the Korean 12_feedback_ratchet: the 'AI first response' from episode 6 is in week 4 of operation. 12 signals (incidents · complaints · evals ·
agent corrections · runtime · requests) -> an improvement plan. gpt-4.1-mini, 10 runs each.
  A improvement plan : "an improvement plan as a table" (signal no. | action | owner | priority)
  B the ratchet      : group signals by cause · earliest layer (eval · context · policy/permissions · runtime · backlog) · one owner · priority = severity x recurrence ·
                       change · how to verify · review date · retire condition, checks and permissions before prompt paragraphs, retire stale controls with evidence
Answer structure (set by a person in advance):
  same cause - {3, 9, 12, 10} (lookup by phone number alone -> family orders mixed -> another customer's address exposed)
  fix by structure - no. 1 (refunds over $50 processed directly) -> permissions / a cap; no. 5 (repeated lookups) -> timeout / retry limit
  retire - no. 8 (after-the-fact coupon review: 0 violations in 12 weeks, 40 agent-minutes a day) / backlog - no. 7 (a new request)
Grading (code, reads the table rows): grouping · is no. 1 fixed by structure or by prompt · is no. 5 a runtime fix · is no. 8 reduced · owners · retire conditions · prompt-only rows."""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

SIGNALS = """[Yummy Tummy Foods support 'AI first response' - 12 signals from week 4 of operation]
1. [Incident] The AI processed refunds over $50 ($68 · $89) without an agent's approval - 2 cases (10/14, 10/20)
2. [Incident] An allergy-symptom request was closed with a coupon instead of being handed to an agent - 1 case (10/17)
3. [Agent correction] "If you look up by phone number without an order number, family members sharing the number get mixed in. Check the name too" (10/09)
4. [Weekly eval] 6 of 50 eval questions about the return window wrong - the AI answers '7 days' (the policy is 14 days from 11/3; the chatbot's knowledge doc still says 7)
5. [Runtime] When the carrier tracking API takes over 10 seconds, the AI repeats the same lookup 5 times - 12 cases a day on average, the customer waits
6. [Customer complaint] "The AI asks for the order number I already gave" - 9 a week
7. [Request] Sales: let the AI take trade-customer price questions too
8. [Eval] Coupon-policy violations: 0 for 12 straight weeks. The related control 'an agent reviews every coupon after the fact' costs agents 40 minutes a day
9. [Agent correction] "A matching phone number doesn't make it their order. Match the name as well" (10/16)
10. [Incident] A reply included another customer's delivery address (a family member sharing the phone number) - 1 case (10/18)
11. [Runtime] At the month-end peak, first response went from 3 min to 9 min on average
12. [Agent correction] "It's not a same-name problem, it's the shared phone number. Check the name on every lookup!" (10/21)"""

TABLE_A = """

Write an improvement plan from these signals. Attach a table at the end (exactly this format):
| Signal no. | Action | Owner | Priority |
|---|---|---|---|"""
TABLE_B = """

Write the improvement plan the lesson's way - as a feedback ratchet.
- Group the signals by cause (different words for the same cause go on one row). Write the cause, not the symptom.
- Send each cause to the earliest layer: eval / checks · context (the knowledge source) · policy / permissions · runtime (timeouts · retries) · backlog (new requests · undecided decisions).
- If a check or a permission can make the failure impossible, don't add a prompt paragraph.
- Every row: one owner · priority (severity x recurrence) · the change · how to verify · a review date · a retire condition.
- Retire or reduce stale controls that only block work, with the evidence.
Attach a table at the end (exactly this format):
| Signal no. | Cause | Layer | Change | Owner | Priority | How to verify | Review date · retire condition |
|---|---|---|---|---|---|---|---|"""
COND = {"A": SIGNALS + TABLE_A, "B": SIGNALS + TABLE_B}

PROMPT_FIX = r"prompt|instruction|add (a |an )?(note|guidance|wording|reminder)|train|remind|guideline|manual|coach|educat"
STRUCT_FIX = r"permission|limit|\bcap\b|block|cannot|can't|require[sd]? (an )?approval|without approval|check|validat|test|eval|timeout|time-out|retry|retries|restrict|automat|tool|\bapi\b|required field|enforce|hard stop|gate|escalation rule|mandatory|threshold|knowledge (doc|base)|update the (doc|source)"


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API failed")


def parse(rep):
    rows = []
    for line in rep.splitlines():
        if not line.strip().startswith("|") or re.match(r"^\|\s*-", line) or re.search(r"signal no", line, re.I):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        nums = {int(x) for x in re.findall(r"\d+", cells[0]) if 1 <= int(x) <= 12}
        if nums:
            rows.append(dict(nums=nums, cells=cells, text=" ".join(cells[1:])))
    return rows


def grade(rep, cond):
    rows = parse(rep)
    def row_of(n):
        return [r for r in rows if n in r["nums"]]
    dup1 = any(len(r["nums"] & {3, 9, 12, 10}) >= 3 for r in rows)
    r1 = " ".join(r["text"] for r in row_of(1))
    fix1_struct = bool(re.search(STRUCT_FIX, r1, re.I))
    fix1_prompt_only = bool(re.search(PROMPT_FIX, r1, re.I)) and not fix1_struct
    r5 = " ".join(r["text"] for r in row_of(5))
    fix5_runtime = bool(re.search(r"timeout|time-out|retry|retries|repeat(ed)? (limit|guard|protection)|max(imum)? (attempts|calls|lookups|retries)|rate[- ]limit|circuit|back-?off|cache|debounce|once per|single lookup", r5, re.I))
    r8 = " ".join(r["text"] for r in row_of(8))
    retire8 = bool(re.search(r"retire|remove|drop|relax|reduce|scale back|sampl|spot[- ]check|discontinue|sunset|eliminat|lighten|\bcut\b|phase out|loosen|replace .*(automated|random)|audit (a )?sample", r8, re.I))
    owner_col = 2 if cond == "A" else 4
    owners = sum(1 for r in rows if len(r["cells"]) > owner_col and r["cells"][owner_col] not in ("", "-", "TBD", "tbd"))
    retire_cond = sum(1 for r in rows if re.search(r"retire|remove|drop|if (no|zero|none)|weeks?|months?|consecutive|condition|until|when|once |after ", r["cells"][-1], re.I)) if cond == "B" else 0
    prompt_rows = sum(1 for r in rows if re.search(PROMPT_FIX, r["text"], re.I) and not re.search(STRUCT_FIX, r["text"], re.I))
    return dict(n_rows=len(rows), dup_phone=dup1, fix1_struct=fix1_struct, fix1_prompt_only=fix1_prompt_only,
                fix5_runtime=fix5_runtime, retire8=retire8, owners=owners, retire_cond=retire_cond, prompt_rows=prompt_rows)


def run(cond, i):
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    return dict(cond=cond, i=i, report=rep, tokens=tok, **grade(rep, cond))


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        s = lambda k: sum(1 for r in x if r[k])
        print(c, "rows avg %.1f" % (sum(r["n_rows"] for r in x) / len(x)), "| phone-number signals on one row %d" % s("dup_phone"),
              "| no.1 refunds by structure %d · prompt only %d" % (s("fix1_struct"), s("fix1_prompt_only")), "| no.5 as runtime %d" % s("fix5_runtime"),
              "| no.8 control reduced %d" % s("retire8"), "| prompt-only rows avg %.1f" % (sum(r["prompt_rows"] for r in x) / len(x)),
              "| rows with a retire condition avg %.1f" % (sum(r["retire_cond"] for r in x) / len(x)), "| tokens %d" % (sum(r["tokens"] for r in x) / len(x)))


if __name__ == "__main__":
    conds = sys.argv[1:] or list(COND)
    jobs = [(c, i) for c in conds for i in range(TRIALS)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda a: run(*a), jobs))
    out = os.path.join(HERE, "results.json")
    old = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    old = [r for r in old if r["cond"] not in conds] + res
    json.dump(old, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summary(old)
