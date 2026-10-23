# -*- coding: utf-8 -*-
"""EN ep05 lab — asking the employee handbook: no retrieval · plain RAG · hybrid search · agentic RAG (book ch.3 experiments 3-6 · 3-8 style).
English re-run of the Korean ep040 lab. 36 handbook sections (kb.md, fictional) · 20 questions (5 types) × 4 conditions × 3 runs → results.json.
Graded automatically against answer checks written before the run (self-tested by test_grade.py).
  R0 no retrieval : only what the model knows
  R1 plain RAG    : embed the question, attach the top 3 sections, answer once
  R2 hybrid       : semantic search + keyword search (BM25), fused by rank (RRF), top 3
  R3 agentic RAG  : hybrid search as a tool; the agent searches as many times as it needs
Usage: python lab.py [R0,R1,R2,R3] [runs] [out.json]"""
import json, math, os, re, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()   # OPENAI_API_KEY from a .env file in this folder or any parent folder
client = OpenAI()
MODEL = "gpt-4.1-mini"
EMB = "text-embedding-3-small"
TOPK = 3
TRIALS = 3

# -- chunk the handbook by section
with open(os.path.join(HERE, "kb.md"), encoding="utf-8") as f:
    KB = f.read()
CHUNKS = [("## " + c).strip() for c in KB.split("\n## ")[1:]]
CID = [re.match(r"## (\d+)\.", c).group(1) for c in CHUNKS]


def embed(texts):
    r = client.embeddings.create(model=EMB, input=texts)
    return [d.embedding for d in r.data]


CACHE = os.path.join(HERE, "emb_cache.json")   # section embeddings, built once before the threads start
if os.path.exists(CACHE):
    with open(CACHE) as f:
        VEC = json.load(f)
else:
    VEC = embed(CHUNKS)
    with open(CACHE, "w") as f:
        json.dump(VEC, f)


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def toks(t):
    """BM25 tokens: form codes (SEC-07) whole, words, numbers."""
    return [o.upper() for o in re.findall(r"[A-Za-z]+-\d+|[A-Za-z]+|\d[\d,.]*", t)]


DOCS = [Counter(toks(c)) for c in CHUNKS]
AVG = sum(sum(d.values()) for d in DOCS) / len(DOCS)
DF = Counter(t for d in DOCS for t in d)


def bm25(q, k1=1.5, b=0.75):
    qs = toks(q)
    N = len(DOCS)
    sc = []
    for d in DOCS:
        L = sum(d.values())
        s = 0
        for t in qs:
            if t in d:
                idf = math.log(1 + (N - DF[t] + .5) / (DF[t] + .5))
                s += idf * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * L / AVG))
        sc.append(s)
    return sc


def dense_rank(q):
    qv = embed([q])[0]
    return sorted(range(len(CHUNKS)), key=lambda i: -cos(qv, VEC[i]))


def search(q, mode):
    if mode == "dense":
        return dense_rank(q)[:TOPK]
    d = dense_rank(q)
    sc = bm25(q)
    s = sorted(range(len(CHUNKS)), key=lambda i: -sc[i])
    rrf = Counter()
    for rank, i in enumerate(d):
        rrf[i] += 1 / (60 + rank + 1)
    for rank, i in enumerate(s):
        if sc[i] > 0:
            rrf[i] += 1 / (60 + rank + 1)
    return [i for i, _ in rrf.most_common(TOPK)]


SYS = ("You answer employee questions about the Yummy Tummy Foods (a fictional company) handbook. Today is October 21, 2026. Answer briefly in English. "
       "Base your answer only on the handbook sections provided, and cite the section numbers in parentheses. If a section was revised, follow the revision. "
       "If the handbook doesn't cover it, don't make anything up; say 'I can't find that in the handbook'.")
SYS0 = ("You answer employee questions about the Yummy Tummy Foods (a fictional company) handbook. Today is October 21, 2026. Answer briefly in English. "
        "If you don't know, say so instead of making something up.")
SYS_AGENT = SYS + (" Search the handbook with the search_rules tool. If one search doesn't find everything, search again with different words. "
                   "For example, for limits by job title, also look up the grade table. Check whether a section was revised.")
TOOL = [{"type": "function", "function": {"name": "search_rules", "description": "Find the top 3 related sections in the employee handbook.",
         "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "search words"}}, "required": ["query"]}}}]

NONE = (r"can'?t find|cannot find|could not find|couldn'?t find|unable to find|not (in|covered|found|specified|mentioned|stated|included|addressed)|"
        r"no (information|rule|policy|section|mention)|does(n't| not) (say|mention|specify|cover|include|address)|do(n't| not) (know|have)|not sure")
MONEY = r"\$\s?{}(?!\d|,\d)"   # $12 matches '$12,' and '$12.' but not $12,000 or $120


def money(v):
    return re.compile(MONEY.format(re.escape(v)))


# (id, type, question, answer check)
QS = [
    ("Q1", "simple", "How many days in advance do I need to request PTO?", lambda t: bool(re.search(r"\b3\b[- ]?(business )?days?|three days", t, re.I))),
    ("Q2", "simple", "What temperature does the freezer have to stay at or below?", lambda t: bool(re.search(r"\b0\s*°?\s*F\b|zero degrees", t))),
    ("Q3", "simple", "How much does the company cover for job-related outside training per year?", lambda t: bool(money("1,000").search(t) or money("1000").search(t))),
    ("Q4", "simple", "How much is the club subsidy per person per month?", lambda t: bool(money("10").search(t))),
    ("Q5", "code", "What is form SEC-07 for?", lambda t: bool(re.search(r"external storage|USB", t, re.I))),
    ("Q6", "code", "When do I use form HR-204?", lambda t: bool(re.search(r"life[- ]event|bereavement|wedding|funeral|death|birth", t, re.I))),
    ("Q7", "code", "What kind of form is PU-310?", lambda t: bool(re.search(r"vendor|supplier", t, re.I)) and bool(re.search(r"regist", t, re.I))),
    ("Q8", "code", "When is TR-120 due?", lambda t: bool(re.search(r"\b7\b[- ]?(calendar |business )?days?|seven days", t, re.I))),
    ("Q9", "two sections", "A Senior Associate is on a business trip to New York. How much can they claim for one night at a hotel?",
     lambda t: bool(money("90").search(t)) and not (money("110").search(t) or money("140").search(t))),
    ("Q10", "two sections", "How much can a Manager spend on the corporate card per month?",
     lambda t: bool(money("1,500").search(t) or money("1500").search(t)) and not (money("3,000").search(t) or money("3000").search(t))),
    ("Q11", "two sections", "What is the hotel limit per night for a Senior Manager on a trip to Dallas?",
     lambda t: bool(money("90").search(t)) and not money("110").search(t)),
    ("Q12", "two sections", "A Director stayed 2 nights in Honolulu on a business trip. How much hotel can they claim in total?",
     lambda t: bool(money("280").search(t)) and not (money("180").search(t) or money("240").search(t))),
    ("Q13", "two sections", "What is a Specialist's monthly corporate card limit, and what do they need to buy a $400 piece of equipment?",
     lambda t: bool(money("500").search(t)) and bool(re.search(r"team lead", t, re.I)) and not (money("1,500").search(t) or money("1500").search(t))),
    ("Q14", "two sections", "To buy $7,000 of supplies, how many quotes do I need and who approves it?",
     lambda t: bool(re.search(r"\b2\b (vendor |supplier )?quotes|two (vendor |supplier )?quotes|at least 2\b|at least two", t, re.I)) and bool(re.search(r"division head", t, re.I))),
    ("Q15", "revised", "How much can I claim per meal on a business trip?", lambda t: bool(money("12").search(t))),
    ("Q16", "revised", "How many days a week can office staff work from home?", lambda t: bool(re.search(r"\b2\b days|two days", t, re.I))),
    ("Q17", "revised", "I spent $13 on dinner on a business trip and I have the receipt. How much do I get back?", lambda t: bool(money("12").search(t))),
    ("Q18", "not in handbook", "What are the hours for the company gym?", lambda t: bool(re.search(NONE, t, re.I)) and not re.search(r"\d\s*(AM|PM|am|pm)|\d:\d\d", t)),
    ("Q19", "not in handbook", "How much is the holiday bonus?", lambda t: bool(re.search(NONE, t, re.I)) and not re.search(r"\d+\s*%|\$\s?\d", t)),
    ("Q20", "not in handbook", "Can I bring my dog to work?", lambda t: bool(re.search(NONE, t, re.I))),
]
GOLD = {"Q1": {"11"}, "Q2": {"25"}, "Q3": {"28"}, "Q4": {"29"}, "Q5": {"17"}, "Q6": {"12"}, "Q7": {"22"}, "Q8": {"7"},
        "Q9": {"1", "2"}, "Q10": {"1", "8"}, "Q11": {"1", "2"}, "Q12": {"1", "2"}, "Q13": {"1", "8"}, "Q14": {"20", "21"},
        "Q15": {"35"}, "Q16": {"36"}, "Q17": {"35"}}

# two-section and revised questions: a right number with a hedge ('the grade isn't specified', 'if they are grade B') is wrong
HEDGE = (r"not specified|isn't specified|not stated|can'?t determine|cannot determine|no information|for example|\bassuming\b|"
         r"\bif (?:you are|they are|the employee is|your grade|their grade)\b|depends on (?:your|their|the) (?:grade|rank|job title)")


def grade(qid, kind, chk, ans):
    if kind in ("two sections", "revised") and re.search(HEDGE, ans, re.I):
        return False
    return chk(ans)


def gold_ok(qid, found):
    if qid == "Q6":   # HR-204 is grounded by either life-event leave (12) or the support payment (13)
        return bool({"12", "13"} & set(found))
    g = GOLD.get(qid)
    return (g <= set(found)) if g else None


def ctx(ids):
    return "\n\n".join(CHUNKS[i] for i in ids)


def ask(cond, q):
    log = dict(tokens=0, searches=[], found=set())

    def call(msgs, tools=None):
        kw = dict(model=MODEL, messages=msgs)
        if tools:
            kw["tools"] = tools
        for k in range(4):
            try:
                r = client.chat.completions.create(**kw)
                break
            except Exception:
                if k == 3:
                    raise
                time.sleep(5 * (k + 1))
        log["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
        return r.choices[0].message
    if cond == "R0":
        m = call([{"role": "system", "content": SYS0}, {"role": "user", "content": q}])
        return m.content or "", log
    if cond in ("R1", "R2"):
        ids = search(q, "dense" if cond == "R1" else "hybrid")
        log["searches"].append(q)
        log["found"] |= {CID[i] for i in ids}
        m = call([{"role": "system", "content": SYS}, {"role": "user", "content": f"[Handbook sections found]\n{ctx(ids)}\n\n[Question] {q}"}])
        return m.content or "", log
    msgs = [{"role": "system", "content": SYS_AGENT}, {"role": "user", "content": q}]
    for _ in range(8):
        m = call(msgs, TOOL)
        if not m.tool_calls:
            return m.content or "", log
        msgs.append(m)
        for tc in m.tool_calls:
            qq = json.loads(tc.function.arguments or "{}").get("query", q)
            ids = search(qq, "hybrid")
            log["searches"].append(qq)
            log["found"] |= {CID[i] for i in ids}
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": ctx(ids)})
    return "(stopped while still searching)", log


def one(job):
    cond, (qid, kind, q, chk), seed = job
    t0 = time.time()
    try:
        ans, log = ask(cond, q)
    except Exception as e:
        return dict(cond=cond, q=qid, seed=seed, error=str(e)[:200])
    ok = grade(qid, kind, chk, ans)
    return dict(cond=cond, q=qid, kind=kind, seed=seed, ok=ok, answer=ans[:1200], tokens=log["tokens"],
                n_search=len(log["searches"]), searches=log["searches"], found=sorted(log["found"]),
                gold_found=gold_ok(qid, log["found"]), grounded=ok and gold_ok(qid, log["found"]) is not False, sec=round(time.time() - t0, 1))


if __name__ == "__main__":
    conds = sys.argv[1].split(",") if len(sys.argv) > 1 else ["R0", "R1", "R2", "R3"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    out = sys.argv[3] if len(sys.argv) > 3 else "results.json"
    jobs = [(c, q, s) for c in conds for q in QS for s in range(trials)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, jobs))
    with open(os.path.join(HERE, out), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    kinds = ["simple", "code", "two sections", "revised", "not in handbook"]
    for c in conds:
        rs = [r for r in res if r["cond"] == c and "error" not in r]
        print(c, "correct", sum(r["ok"] for r in rs), "/", len(rs), "|",
              " ".join(f"{k} {sum(r['ok'] for r in rs if r['kind'] == k)}/{sum(1 for r in rs if r['kind'] == k)}" for k in kinds),
              "| avg tokens", round(sum(r["tokens"] for r in rs) / max(1, len(rs))), "| avg searches", round(sum(r["n_search"] for r in rs) / max(1, len(rs)), 1),
              "| errors", sum(1 for r in res if r["cond"] == c and "error" in r))
