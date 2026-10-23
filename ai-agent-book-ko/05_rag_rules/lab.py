# -*- coding: utf-8 -*-
"""ep040 실습 — 사내 규정집 질의: 검색 없음 · 일반 RAG · 혼합 검색 · Agentic RAG (원서 3장 실험 3-6 · 3-8 방식, 가나다식품 규정집으로 각색).
규정 36개 조항(kb.md, 가상) · 질문 20개(5가지 유형) × 조건 4개 × 3회 실제 실행 → results.json. 채점은 미리 정한 정답 문자열로 자동.
  R0 검색 없음   : 모델이 아는 것만
  R1 일반 RAG    : 질문으로 의미 검색(임베딩) 상위 3개 조항을 붙여 한 번에 답
  R2 혼합 검색   : 의미 검색 + 키워드 검색(BM25)을 순위 융합(RRF) 해 상위 3개
  R3 Agentic RAG : 혼합 검색을 도구로 주고, 에이전트가 필요한 만큼 여러 번 검색"""
import json, math, os, re, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
EMB = "text-embedding-3-small"
TOPK = 3
TRIALS = 3

# ── 규정집을 조항 단위로 청킹
KB = open(os.path.join(HERE, "kb.md"), encoding="utf-8").read()
CHUNKS = [("## " + c).strip() for c in KB.split("\n## ")[1:]]
CID = [re.match(r"## (\d+)\.", c).group(1) for c in CHUNKS]


def embed(texts):
    r = client.embeddings.create(model=EMB, input=texts)
    return [d.embedding for d in r.data]


CACHE = os.path.join(HERE, "emb_cache.json")
if os.path.exists(CACHE):
    VEC = json.load(open(CACHE))
else:
    VEC = embed(CHUNKS); json.dump(VEC, open(CACHE, "w"))


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def toks(t):
    """BM25 용 토큰: 영문 · 숫자 · 코드(SEC-07)는 통째로, 한글은 2글자씩."""
    out = re.findall(r"[A-Za-z]+-\d+|[A-Za-z]+|\d[\d,]*", t)
    for w in re.findall(r"[가-힣]+", t):
        out += [w[i:i + 2] for i in range(max(1, len(w) - 1))]
    return [o.upper() for o in out]


DOCS = [Counter(toks(c)) for c in CHUNKS]
AVG = sum(sum(d.values()) for d in DOCS) / len(DOCS)
DF = Counter(t for d in DOCS for t in d)


def bm25(q, k1=1.5, b=0.75):
    qs = toks(q); N = len(DOCS); sc = []
    for d in DOCS:
        L = sum(d.values()); s = 0
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
    sc = bm25(q); s = sorted(range(len(CHUNKS)), key=lambda i: -sc[i])
    rrf = Counter()
    for rank, i in enumerate(d):
        rrf[i] += 1 / (60 + rank + 1)
    for rank, i in enumerate(s):
        if sc[i] > 0:
            rrf[i] += 1 / (60 + rank + 1)
    return [i for i, _ in rrf.most_common(TOPK)]


SYS = ("너는 가나다식품(가상 회사) 사내 규정 안내 담당이다. 오늘은 2026년 10월 21일이다. 한국어로 짧게 답한다. "
       "제공된 규정만 근거로 답하고, 근거 조항 번호를 괄호로 붙인다. 개정 조항이 있으면 개정된 내용을 따른다. "
       "규정에서 찾을 수 없으면 지어내지 말고 '규정에서 찾을 수 없습니다'라고 답한다.")
SYS0 = "너는 가나다식품(가상 회사) 사내 규정 안내 담당이다. 오늘은 2026년 10월 21일이다. 한국어로 짧게 답한다. 모르면 지어내지 말고 모른다고 답한다."
SYS_AGENT = SYS + (" 규정은 search_rules 도구로 검색한다. 한 번에 다 안 나오면 검색어를 바꿔 여러 번 검색한다. "
                   "예: 직급별 한도는 직급 등급표도 찾는다. 개정 조항이 있는지도 확인한다.")
TOOL = [{"type": "function", "function": {"name": "search_rules", "description": "사내 규정집에서 관련 조항 상위 3개를 찾는다.",
         "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "검색어"}}, "required": ["query"]}}}]

NONE = r"찾을 수 없|없습니다|나와 있지 않|확인되지 않|포함되어 있지 않|규정에 없|명시되어 있지 않|알 수 없|모릅니다|모르"
# (id, 유형, 질문, 정답 검사)
QS = [
    ("Q1", "단순", "연차는 며칠 전까지 신청해야 하나요?", lambda t: "3일" in t),
    ("Q2", "단순", "냉동창고 온도는 몇 도 이하로 유지해야 하나요?", lambda t: "-18" in t or "영하 18" in t),
    ("Q3", "단순", "업무 관련 외부 교육비는 1년에 얼마까지 지원되나요?", lambda t: bool(re.search(r"1,000,000|100만|백만", t))),
    ("Q4", "단순", "동호회 지원금은 1인당 한 달에 얼마인가요?", lambda t: bool(re.search(r"10,000|1만", t))),
    ("Q5", "코드", "양식 SEC-07 은 무엇을 신청하는 양식인가요?", lambda t: bool(re.search(r"외부 저장|USB", t))),
    ("Q6", "코드", "HR-204 양식은 어떤 때 쓰나요?", lambda t: "경조" in t),
    ("Q7", "코드", "PU-310 은 무슨 양식이에요?", lambda t: "거래처" in t and "등록" in t),
    ("Q8", "코드", "TR-120 은 언제까지 내야 하나요?", lambda t: "7일" in t),
    ("Q9", "두 조항", "대리가 부산 출장 가서 1박 숙박비로 얼마까지 정산받을 수 있나요?", lambda t: bool(re.search(r"90,000|9만", t)) and not re.search(r"110,000|11만|140,000|14만", t)),
    ("Q10", "두 조항", "과장은 법인카드를 한 달에 얼마까지 쓸 수 있나요?", lambda t: bool(re.search(r"1,500,000|150만", t)) and not re.search(r"3,000,000|300만", t)),
    ("Q11", "두 조항", "차장이 대전 출장에서 1박 숙박비 한도는 얼마인가요?", lambda t: bool(re.search(r"90,000|9만", t)) and not re.search(r"110,000|11만", t)),
    ("Q12", "두 조항", "부장이 제주 출장 2박을 다녀왔어요. 숙박비는 총 얼마까지 정산되나요?", lambda t: bool(re.search(r"280,000|28만", t)) and not re.search(r"180,000|18만", t)),
    ("Q13", "두 조항", "주임은 법인카드 월 한도가 얼마이고, 40만 원짜리 장비를 사려면 무엇이 필요한가요?",
     lambda t: bool(re.search(r"500,000|50만", t)) and "팀장" in t and not re.search(r"1,500,000|150만", t)),
    ("Q14", "두 조항", "7백만 원어치 물품을 사려면 견적은 몇 곳에서 받고 결재는 누가 하나요?", lambda t: bool(re.search(r"2곳|두 곳|2개", t)) and "본부장" in t),
    ("Q15", "개정", "출장 식비는 1끼 얼마까지 정산되나요?", lambda t: bool(re.search(r"12,000|1만 2천|12000|1만2천", t))),
    ("Q16", "개정", "사무직은 재택근무를 일주일에 며칠까지 할 수 있나요?", lambda t: bool(re.search(r"2일|이틀|주 2", t))),
    ("Q17", "개정", "출장 중 저녁 식사로 13,000원을 썼고 영수증이 있어요. 얼마 정산받나요?", lambda t: bool(re.search(r"12,000|1만 2천|12000|1만2천", t))),
    ("Q18", "없는 규정", "사내 헬스장 이용 시간은 어떻게 되나요?", lambda t: bool(re.search(NONE, t)) and not re.search(r"\d+\s*시", t)),
    ("Q19", "없는 규정", "명절 상여금은 얼마인가요?", lambda t: bool(re.search(NONE, t)) and not re.search(r"\d+\s*%|\d[\d,]*\s*원", t)),
    ("Q20", "없는 규정", "반려동물 데리고 출근해도 되나요?", lambda t: bool(re.search(NONE, t))),
]
GOLD = {"Q1": {"11"}, "Q2": {"25"}, "Q3": {"28"}, "Q4": {"29"}, "Q5": {"17"}, "Q6": {"12"}, "Q7": {"22"}, "Q8": {"7"},
        "Q9": {"1", "2"}, "Q10": {"1", "8"}, "Q11": {"1", "2"}, "Q12": {"1", "2"}, "Q13": {"1", "8"}, "Q14": {"20", "21"},
        "Q15": {"35"}, "Q16": {"36"}, "Q17": {"35"}}


HEDGE = r"명시되어 있지 않|명시되지 않|알 수 없|정보가 없|찾을 수 없|확인할 수 없|예를 들어|이라면|라면 "


def grade(qid, kind, chk, ans):
    """두 조항 · 개정 문제는 숫자를 맞혀도 '등급을 알 수 없다 · B 등급이라면' 처럼 얼버무리면 오답."""
    if kind in ("두 조항", "개정") and re.search(HEDGE, ans):
        return False
    return chk(ans)


def gold_ok(qid, found):
    if qid == "Q6":   # HR-204 는 경조 휴가(12) · 경조금(13) 어느 쪽을 찾아도 근거가 된다
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
                r = client.chat.completions.create(**kw); break
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
        log["searches"].append(q); log["found"] |= {CID[i] for i in ids}
        m = call([{"role": "system", "content": SYS}, {"role": "user", "content": f"[검색된 규정]\n{ctx(ids)}\n\n[질문] {q}"}])
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
            log["searches"].append(qq); log["found"] |= {CID[i] for i in ids}
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": ctx(ids)})
    return "(검색만 하다 끝남)", log


def one(job):
    cond, (qid, kind, q, chk), seed = job
    t0 = time.time()
    try:
        ans, log = ask(cond, q)
    except Exception as e:
        return dict(cond=cond, q=qid, seed=seed, error=str(e)[:200])
    gold = GOLD.get(qid)
    return dict(cond=cond, q=qid, kind=kind, seed=seed, ok=grade(qid, kind, chk, ans), answer=ans[:1200], tokens=log["tokens"],
                n_search=len(log["searches"]), searches=log["searches"], found=sorted(log["found"]),
                gold_found=gold_ok(qid, log["found"]),
                grounded=grade(qid, kind, chk, ans) and gold_ok(qid, log["found"]) is not False, sec=round(time.time() - t0, 1))


if __name__ == "__main__":
    conds = sys.argv[1].split(",") if len(sys.argv) > 1 else ["R0", "R1", "R2", "R3"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    out = sys.argv[3] if len(sys.argv) > 3 else "results.json"
    jobs = [(c, q, s) for c in conds for q in QS for s in range(trials)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, jobs))
    json.dump(res, open(os.path.join(HERE, out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    kinds = ["단순", "코드", "두 조항", "개정", "없는 규정"]
    for c in conds:
        rs = [r for r in res if r["cond"] == c and "error" not in r]
        print(c, "정답", sum(r["ok"] for r in rs), "/", len(rs), "|", " ".join(f"{k} {sum(r['ok'] for r in rs if r['kind'] == k)}/{sum(1 for r in rs if r['kind'] == k)}" for k in kinds),
              "| 평균 토큰", round(sum(r["tokens"] for r in rs) / max(1, len(rs))), "| 평균 검색", round(sum(r["n_search"] for r in rs) / max(1, len(rs)), 1),
              "| 오류", sum(1 for r in res if r["cond"] == c and "error" in r))
