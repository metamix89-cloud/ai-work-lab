# -*- coding: utf-8 -*-
"""EN es09 lab — Build an evidence-backed execution plan (source: AI Engineering from Scratch, Phase 14 lesson 44).
English re-run of the Korean 09_evidence_plan: Yummy Tummy Foods (fictional) changes the frozen-returns window from 7 to 14 days. 6 background facts; the AI writes the execution plan. gpt-4.1-mini, 10 runs each.
  A plan only       : "write the execution plan" + a sequence table at the end (No. | task | must finish first)
  B the lesson's way : per item number · the smallest change · evidence (which fact) · what must finish first · evidence of done; order by dependency;
                       independent work in the same wave; irreversible work after its uncertainties are resolved - same table
  C B + a check after planning : for every irreversible item, "right after it's done, what does the other side (customer, staff) do next - what must already be finished for that to succeed?" -> add it as a dependency
Grading (code - reads the sequence table, groups tasks by kind, follows the dependencies):
  1) is the customer SMS (irreversible) after Legal sign-off and after the system setting change  2) is the website notice after Legal
  3) did evidence change the plan: template reused · opted-in customers only · no Friday deployment  4) independent work in the same wave (wave count).
The Korean run found code grading unreliable for 'prep + send' mixed lines and judged all 30 tables by hand; see manual.py."""
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

FACTS = """[Background - Yummy Tummy Foods: frozen returns window 7 -> 14 days]
1. Management decision (10/20): the return window for frozen items goes from 7 to 14 days after delivery. Effective 11/3 (Mon).
2. Legal: the new return-policy wording is finalized after Legal review. Reply expected 10/28.
3. IT: the returns intake screen blocks requests 'more than 7 days after delivery'. The setting has to be changed. No deployments on Fridays.
4. Marketing: there is a customer-notice template (website + SMS) from the March shipping-fee change.
5. Privacy policy: the SMS notice may go only to customers who opted in to marketing messages (about 12,000 of 20,000). Once sent, an SMS cannot be recalled.
6. The support-agent manual and the AI chatbot's wording both say '7 days'. Agent training happens after the manual is updated."""

TABLE_ASK = """

At the very end, attach the sequence table (exactly this format):
| No. | Task | Must finish first (No.) |
|---|---|---|
| 1 | ... | - |"""

A = FACTS + "\n\nWrite the execution plan for this change." + TABLE_ASK
B = FACTS + """

Write the execution plan for this change the lesson's way.
- For every task: number · the change (the smallest one) · evidence (which fact above) · the numbers that must finish first · evidence of done (what shows it's finished)
- Order by dependency, not by prose order. Work with no dependency goes in the same wave.
- When several places depend on the same content (wording), finalize that content first.
- Irreversible work goes after every uncertainty it depends on is resolved.
- Evidence counts only if it can change the plan - find the facts above that change the plan, and reflect them.""" + TABLE_ASK

C = B.replace(TABLE_ASK, "") + """
- After planning, check it. The lesson: duplicate numbers · no evidence · no done-evidence · a dependency on a missing number · cycles are caught mechanically,
  but 'does an irreversible task come before an uncertainty' needs judgment - check it separately.
  For every irreversible task: right after it's done, what does the other side (a customer, an employee) do next? What must already be finished for that to succeed? -> add that as a dependency.""" + TABLE_ASK
COND = {"A": A, "B": B, "C": C}

KINDS = [   # group the table's 'Task' by kind (first match wins)
    # only the actual send counts as 'sms' - 'prepare / draft the SMS' is prep (the Korean grader first lumped them together and mis-counted)
    ("sms", r"^(?!.*\b(prepar\w*|draft\w*|write|writ\w*|edit\w*|select\w*|request\w*|review\w*|wording|template|plan\w*|finali[sz]\w*|approv\w*|segment\w*|build\w*|compil\w*|confirm\w*|extract\w*|pull\w*|schedul\w*)\b).*(\b(send|sends|sending|dispatch\w*|blast|broadcast\w*|deliver\w*|push\w*)\b.*\b(sms|text)|\b(sms|text)\b.*\b(send|sends|sending|dispatch\w*|blast|broadcast\w*|go(es)? out)\b)"),
    ("smsprep", r"\bsms\b|text message|\btext\b|customer notice|notif"),
    ("legal", r"\blegal\b"),
    ("web", r"website|web page|homepage|\bweb\b|post\w* (the )?notice|publish"),
    ("system", r"system|setting|intake screen|\bIT\b|deploy|configur|return window (in|on) the"),
    ("bot", r"chatbot|\bbot\b"),
    ("manual", r"manual"),
    ("train", r"training|\btrain\b"),
]


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API failed")


def parse_table(rep):
    rows = {}
    for line in rep.splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*$", line)
        if m:
            rows[int(m.group(1))] = (m.group(2), [int(x) for x in re.findall(r"\d+", m.group(3))])
    return rows


def kind_of(task):
    for k, pat in KINDS:
        if re.search(pat, task, re.I):
            return k
    return "other"


def ancestors(rows, n, seen=None):
    seen = seen if seen is not None else set()
    for d in rows.get(n, ("", []))[1]:
        if d in rows and d not in seen:
            seen.add(d)
            ancestors(rows, d, seen)
    return seen


def waves(rows):
    lvl = {}
    def L(n, stack=()):
        if n in lvl:
            return lvl[n]
        if n in stack:
            return 99   # cycle
        deps = [d for d in rows[n][1] if d in rows]
        lvl[n] = 1 + max([L(d, stack + (n,)) for d in deps], default=0)
        return lvl[n]
    for n in rows:
        L(n)
    return max(lvl.values()) if lvl else 0


SYSTEM_RE = re.compile(KINDS[[k for k, _ in KINDS].index("system")][1], re.I)


def grade(rep):
    rows = parse_table(rep)
    kinds = {n: kind_of(t) for n, (t, _) in rows.items()}
    def before(target, need):
        ts = [n for n, k in kinds.items() if k == target]
        ns = [n for n, k in kinds.items() if k == need]
        if not ts or not ns:
            return None
        # 'deploy the setting and send the SMS' written on one line counts as the same wave
        same = lambda t: need == "system" and SYSTEM_RE.search(rows[t][0])
        return all(same(t) or any(x in ancestors(rows, t) for x in ns) for t in ts)
    return dict(n_rows=len(rows), kinds=kinds,
                sms_after_legal=before("sms", "legal"), sms_after_system=before("sms", "system"),
                web_after_legal=before("web", "legal"),
                template=bool(re.search(r"template", rep, re.I)),
                consent=bool(re.search(r"opt(ed)?[- ]in|consent|12,?000", rep, re.I)),
                friday=bool(re.search(r"friday", rep, re.I)),
                waves=waves(rows) if rows else 0)


def run(cond, i):
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    return dict(cond=cond, i=i, report=rep, tokens=tok, **grade(rep))


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        s = lambda k: sum(1 for r in x if r[k] is True)
        print(c, "table parsed %d/%d" % (sum(1 for r in x if r["n_rows"] >= 4), len(x)),
              "| SMS after legal %d · after system %d" % (s("sms_after_legal"), s("sms_after_system")),
              "| website after legal %d" % s("web_after_legal"),
              "| template %d · opt-in %d · friday %d" % (s("template"), s("consent"), s("friday")),
              "| waves avg %.1f · items %.1f" % (sum(r["waves"] for r in x) / len(x), sum(r["n_rows"] for r in x) / len(x)),
              "| tokens %d" % (sum(r["tokens"] for r in x) / len(x)))


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
