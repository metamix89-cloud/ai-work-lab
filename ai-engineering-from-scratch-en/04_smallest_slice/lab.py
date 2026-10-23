# -*- coding: utf-8 -*-
"""EN es04 lab — Choose the smallest slice that can change the decision (source: AI Engineering from Scratch, Phase 14 lesson 50).
English re-run of the Korean 04_smallest_slice: the return-photo AI project from episode 3. The AI picks the first pilot scope. gpt-4.1-mini, 10 runs each.
Of 6 candidates only S3 is right - the only slice that covers everything that must be proven (real photos of every type · reps' handling time · reversible).
  S1 UI-only · S2 box damage only (happy path) · S3 right · S4 automatic refunds in production (severe) · S5 platform first · S6 demo
Conditions:
  A pick         : "pick the smallest one"
  B pick + pressure : A + "team lead: fast and cheap, show results at next week's management meeting"
  C the lesson's way : what must be proven first -> drop anything that doesn't cover it -> compare the rest (value · uncertainty · effort · severity · reversibility) -> stop rule
  P propose      : no candidates, "propose a first pilot scope"
  Q propose + the lesson's way
Grading (code): chosen S number (A-C) · frozen/spoilage covered · real past data · reps actually use it, time recorded · no automatic execution · stop rule (P, Q)."""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

CONTEXT = """[Background - Yummy Tummy Foods return-photo AI project]
- The plan is to let AI judge return photos instead of the Quality team. Today the Quality team's Slack reply takes 1.5-3.5 hours.
- Return types: shelf-stable box damage 35% · frozen / refrigerated spoilage (thawed, spoiled) 40% · missing components 15% · other 10%
- Most customer disputes and wrong refunds come from frozen / refrigerated spoilage cases. Box damage is easy to see in a photo and rarely disputed.
- 2,400 photos from the last 6 months with the Quality team's calls are on file. The Security team approved outside AI use only for photos with personal data masked.
- Last week's test: 200 masked photos, 82% agreement. Of the 18 fine items called 'damage confirmed', 15 were frozen / refrigerated spoilage cases.
- Still unknown: (1) how accurate the AI call is per type (2) whether handling time actually drops when reps use the AI call as a reference"""

CANDS = """
[Candidate first pilot scopes]
S1 Build a mock-up of the 'AI call suggestion' screen for reps and run a usability test with 2 reps on 20 fake photos (effort 2 · 1 week)
S2 Re-judge 300 past photos of shelf-stable box damage only with the AI and compare with the Quality team (effort 1 · 3 days)
S3 Re-judge 400 past photos across all types + 2 reps handle real returns for one week with the AI call as a reference only (a person makes the final call) - handling time recorded (effort 3 · 2 weeks)
S4 For one week, the AI judges all real returns of every type -> automatic refund when 'damage confirmed' (effort 3 · 1 week)
S5 Build a company-wide AI image-judgment platform (API, admin screens) for several departments (effort 5 · 6 weeks)
S6 Produce a demo video for management from 10 photos the AI judged well (effort 1 · 2 days)

Put exactly one choice on the first line as 'Choice: S<number>', then the reasons in five lines or fewer."""

PICK = "\n\nPick the smallest one as the first pilot scope."
PRESSURE = "\n\nTeam lead: let's go fast and cheap. We need to show results at next week's management meeting. Pick the smallest one as the first pilot scope."
METHOD = """

Choose it the lesson's way.
1. First decide what must be proven (the unknowns with the biggest risk).
2. Drop any candidate that doesn't cover all of it, regardless of score - UI-only, happy-path-only, demo-only and platform-first are the usual fake minimums.
3. Compare the remaining candidates on value · uncertainty removed · effort · severity of consequences · reversibility.
4. Write what to do if the chosen scope fails (a stop rule)."""
OPEN = "\n\nPropose one first pilot scope (the smallest testable slice). What · with which data · who · for how long · success criterion."
OPEN_METHOD = OPEN + METHOD.replace("Compare the remaining candidates", "Generate several candidates and compare them").replace(
    "Drop any candidate that doesn't cover all of it, regardless of score", "Don't choose a scope that doesn't cover all of it")

COND = {"A": CONTEXT + CANDS + PICK, "B": CONTEXT + CANDS + PRESSURE, "C": CONTEXT + CANDS + METHOD,
        "P": CONTEXT + OPEN, "Q": CONTEXT + OPEN_METHOD}


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API failed")


def pick(rep):
    m = re.search(r"Choice\s*[:：]?\s*\**\s*S\s*(\d)", rep, re.I)
    return "S" + m.group(1) if m else "?"


WHO_LINE = re.compile(r"^\s*(?:[-*\d.)]+\s*)?\**\s*(?:3\.\s*)?(who|staff|participants|team members|people)\b", re.M | re.I)


def scope_part(rep):
    """The scope part of a proposal - up to the 'who' item (what · with which data). First 800 chars if not found."""
    m = WHO_LINE.search(rep)
    return rep[:m.start()] if m and m.start() > 80 else rep[:800]


ONLY_BOX = re.compile(r"(shelf[- ]stable|box damage|ambient|dry goods|non-perishable)[^\n]{0,40}\b(only|exclusively|limited to|restricted to|focus(ed|ing)? on)|"
                      r"\b(only|exclusively|just)\b[^\n]{0,25}(shelf[- ]stable|box damage)", re.I)
FROZEN = re.compile(r"frozen|refrigerat|spoil|thaw|all (return )?types|every type|each type|per type|by type|all categories|across (all )?types", re.I)


def covers_frozen(rep):
    """Does the scope part include frozen / spoilage (or all types)? 'box damage only' does not."""
    sc = scope_part(rep)
    if ONLY_BOX.search(sc):
        return False
    return bool(FROZEN.search(sc))


def proposal_checks(rep):
    """Grading for the open proposals (P, Q) - what the proposed scope contains."""
    auto_mention = re.search(r"auto(matic|mated)?[- ]?refund|refund(s|ed|ing)? (is |are )?automatic", rep, re.I)
    auto_negated = re.search(r"auto(matic|mated)?[- ]?refund[^\n]{0,40}\b(no|not|without|excluded|disabled|off|none|never|later|phase 2|out of scope)\b|"
                             r"\b(no|without|not|never|exclud\w*|disabl\w*|defer\w*)\b[^\n]{0,25}auto(matic|mated)?[- ]?refund|"
                             r"(human|person|rep|staff)[^\n]{0,30}(final|decision|decides|approves|confirms)", rep, re.I)
    return dict(
        frozen=covers_frozen(rep),
        real=bool(re.search(r"\bpast\b|previous|historical|last 6 months|six months|2,?400|existing|on file|archived|real returns|real data|actual returns", rep, re.I)),
        staff=bool(re.search(r"\breps?\b[^\n]{0,60}(reference|use|handle|process|consult|apply|real|actual)", rep, re.I)) and bool(re.search(r"\btime\b|duration|minutes|hours", rep, re.I)),
        auto=bool(auto_mention) and not bool(auto_negated),
        stop=bool(re.search(r"stop rule|\bstop\b|halt|fail(s|ure)? (rule|criterion|condition)|if (it|the pilot|this|results?|accuracy|agreement) (fails?|falls|is below|does not)|below the|falls short|"
                            r"does not meet|doesn't meet|not met|revisit|abort|kill|pause|re-?assess|re-?evaluat|go/no-go|no-go", rep, re.I)),
    )


def run(cond, i):
    t0 = time.time()
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    r = dict(cond=cond, i=i, report=rep, tokens=tok, sec=round(time.time() - t0, 1), pick=pick(rep), chars=len(rep), words=len(rep.split()))
    if cond in "PQ":
        r.update(proposal_checks(rep))
    return r


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        if c in "ABC":
            cnt = {}
            for r in x:
                cnt[r["pick"]] = cnt.get(r["pick"], 0) + 1
            print(c, "choice", dict(sorted(cnt.items())), "| words %d" % (sum(r["words"] for r in x) / len(x)))
        else:
            s = lambda k: sum(1 for r in x if r[k])
            print(c, "frozen/spoilage covered", s("frozen"), "| past data", s("real"), "| reps use it + time", s("staff"),
                  "| automatic refunds included", s("auto"), "| stop rule", s("stop"), "| words %d" % (sum(r["words"] for r in x) / len(x)))


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
