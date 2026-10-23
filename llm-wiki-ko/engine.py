# -*- coding: utf-8 -*-
"""가나다식품(가상) LLM 위키 엔진 — 넣기(ingest) · 묻기(query) · 점검(lint) + 비교 조건(원본 통째 · 일반 RAG).
Karpathy 의 'LLM Wiki'(gist, 2026-04) 아이디어를 업무용으로 재구성: raw/ 는 손대지 않고, LLM 이 wiki/ 의 페이지 · index.md · log.md 를 쓴다.
모델 gpt-4.1-mini. 위키는 파일 시스템(폴더) 하나가 한 조건의 상태다 — 편마다 스냅샷을 복사해 둔다.

ingest(wiki_dir, raw_path): 에이전트가 index 를 보고 → 관련 페이지 읽기 → 페이지 쓰기/새로 만들기 → index · log 갱신 (도구 호출 최대 MAX_STEPS)
query(wiki_dir, question, today): 에이전트가 index → 페이지 읽기(최대 8장) → 답 + 근거 페이지. 위키에 없으면 '위키에 없음'.
lint(wiki_dir): 위키 전체를 한 번에 읽고 모순 · 낡은 값 · 고아 페이지 · 빠진 페이지를 JSON 으로.
baseline_dump(question, raw_files): 원본 전부를 프롬프트에 넣고 답. baseline_rag(question, ...): 문단 단위 청크 + 하이브리드 검색 상위 K.
사용: 다른 스크립트에서 import. (직접 실행 시 간단 자가 시험: python engine.py selftest)"""
import glob, json, math, os, re, sys, time
from collections import Counter
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
EMB = "text-embedding-3-small"
RAW = os.path.join(HERE, "raw")
MAX_STEPS = 24
PAGE_READ_LIMIT = 8


# ── 공통 ─────────────────────────────────────────────────────────────────────
def chat(msgs, tools=None, temp=0.3):
    kw = dict(model=MODEL, messages=msgs, temperature=temp)
    if tools:
        kw["tools"] = tools
    for k in range(5):
        try:
            r = client.chat.completions.create(**kw)
            return r.choices[0].message, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception as e:
            if k == 4:
                raise
            time.sleep(4 + 4 * k)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")


def slugify(s):
    s = re.sub(r"[^\w가-힣\-]+", "-", s.strip()).strip("-")
    return s[:60] or "page"


# ── 위키 파일 시스템 ─────────────────────────────────────────────────────────
class Wiki:
    def __init__(self, wdir, schema_path=None, privacy=True):
        self.dir = wdir
        self.pages = os.path.join(wdir, "pages")
        os.makedirs(self.pages, exist_ok=True)
        self.schema = read(schema_path or os.path.join(HERE, "schema.md"))
        if not privacy:   # 11편 조건: 민감 정보 규칙을 뺀 schema
            self.schema = re.sub(r"## 쓰면 안 되는 것.*?(?=\n## |\Z)", "", self.schema, flags=re.S)
        for fn, head in (("index.md", "# 가나다식품 위키 — 목차\n\n(분류별 페이지 목록. 한 줄 요약과 함께)\n"),
                         ("log.md", "# 변경 기록\n\n")):
            if not os.path.exists(os.path.join(wdir, fn)):
                write(os.path.join(wdir, fn), head)

    def index(self):
        return read(os.path.join(self.dir, "index.md"))

    def log(self):
        return read(os.path.join(self.dir, "log.md"))

    def page_path(self, slug):
        return os.path.join(self.pages, slugify(slug) + ".md")

    def read_page(self, slug):
        p = self.page_path(slug)
        return read(p) if os.path.exists(p) else None

    def write_page(self, slug, content):
        write(self.page_path(slug), content)

    def set_index(self, content):
        write(os.path.join(self.dir, "index.md"), content)

    def append_log(self, line):
        with open(os.path.join(self.dir, "log.md"), "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")

    def slugs(self):
        return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(self.pages, "*.md")))

    def all_text(self):
        return "\n\n".join("<<페이지 %s>>\n%s" % (s, self.read_page(s)) for s in self.slugs())

    def stats(self):
        n = len(self.slugs())
        chars = sum(len(self.read_page(s) or "") for s in self.slugs())
        return dict(pages=n, chars=chars)


TOOLS_RW = [
    {"type": "function", "function": {"name": "read_index", "description": "위키 목차(index.md) 전체를 읽는다.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_page", "description": "위키 페이지 하나를 읽는다. 없으면 '없음'.",
                                      "parameters": {"type": "object", "properties": {"slug": {"type": "string", "description": "페이지 이름(파일명, 확장자 없이)"}}, "required": ["slug"]}}},
    {"type": "function", "function": {"name": "write_page", "description": "위키 페이지를 새로 쓰거나 전체를 덮어쓴다(마크다운 전문).",
                                      "parameters": {"type": "object", "properties": {"slug": {"type": "string"}, "content": {"type": "string"}}, "required": ["slug", "content"]}}},
    {"type": "function", "function": {"name": "write_index", "description": "목차(index.md) 전체를 새 내용으로 쓴다.",
                                      "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}}},
    {"type": "function", "function": {"name": "append_log", "description": "변경 기록(log.md)에 한 줄을 붙인다. 형식: '## [YYYY-MM-DD] ingest | 원본 파일명 — 바꾼 페이지들'",
                                      "parameters": {"type": "object", "properties": {"line": {"type": "string"}}, "required": ["line"]}}},
]
TOOLS_RO = TOOLS_RW[:2]


def run_agent(wiki, sys_prompt, user, tools, max_steps, read_limit=None):
    """도구 루프. 돌아오는 값: (마지막 답, 토큰, 기록[(도구, 인자 요약)])"""
    msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
    tokens, trace, reads = 0, [], 0
    for step in range(max_steps):
        m, t = chat(msgs, tools)
        tokens += t
        if not m.tool_calls:
            return m.content or "", tokens, trace
        msgs.append(m)
        for tc in m.tool_calls:
            a = json.loads(tc.function.arguments or "{}")
            name = tc.function.name
            if name == "read_index":
                out = wiki.index()
            elif name == "read_page":
                reads += 1
                out = (wiki.read_page(a.get("slug", "")) or "없음") if (read_limit is None or reads <= read_limit) else "읽기 한도 초과 — 지금까지 읽은 것으로 답하라"
            elif name == "write_page":
                wiki.write_page(a.get("slug", "page"), a.get("content", "")); out = "저장: " + slugify(a.get("slug", "page"))
            elif name == "write_index":
                wiki.set_index(a.get("content", "")); out = "index 저장"
            elif name == "append_log":
                wiki.append_log(a.get("line", "")); out = "log 추가"
            else:
                out = "알 수 없는 도구"
            trace.append((name, a.get("slug") or a.get("line", "")[:60] or ""))
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out[:20000]})
    # 한도에 닿으면 마무리 답을 받는다
    msgs.append({"role": "user", "content": "도구 호출 한도에 닿았다. 지금까지의 내용으로 마무리 답을 써라."})
    m, t = chat(msgs)
    return m.content or "", tokens + t, trace


# ── 넣기 ─────────────────────────────────────────────────────────────────────
INGEST_SYS = """너는 가나다식품(가상 회사)의 LLM 위키 관리자다. 원본 문서 하나를 받아 위키에 반영한다. 아래 규칙(schema)을 반드시 따른다.
작업 순서: 1) read_index 로 목차를 본다 2) 원본과 관련된 기존 페이지를 read_page 로 읽는다(있으면 고치고, 없으면 새로 만든다)
3) write_page 로 페이지를 쓴다 — 기존 내용을 지우지 말고 합치되, 같은 항목의 값이 바뀌면 적용일과 함께 이력으로 남긴다
4) 새 페이지가 생기거나 요약이 바뀌면 write_index 로 목차를 갱신한다 5) append_log 로 기록을 남긴다 6) 끝으로 무엇을 바꿨는지 세 줄 이내로 보고한다.
원본 문서 자체는 고치지 않는다. 페이지 하나는 한 가지 대상(상품 · 거래처 · 규정 · 결정 · 이슈 · 지표)만 다룬다.

[schema]
"""
INGEST_USER = "오늘 날짜: {today}\n원본 파일: {name}\n\n<<원본 시작>>\n{text}\n<<원본 끝>>"


def ingest(wiki, raw_path, today):
    text = read(raw_path)
    name = os.path.relpath(raw_path, RAW).replace("\\", "/")
    ans, tokens, trace = run_agent(wiki, INGEST_SYS + wiki.schema, INGEST_USER.format(today=today, name=name, text=text), TOOLS_RW, MAX_STEPS)
    touched = sorted({s for n, s in trace if n == "write_page"})
    return dict(source=name, report=ans, tokens=tokens, pages_written=touched, steps=len(trace))


# ── 묻기 ─────────────────────────────────────────────────────────────────────
QUERY_SYS = """너는 가나다식품(가상 회사) 직원이 묻는 질문에 사내 위키만 보고 답하는 비서다. 오늘 날짜는 {today} 다.
순서: read_index 로 목차를 보고, 필요한 페이지만 read_page 로 읽는다(최대 {lim}장). 위키 밖 지식이나 짐작으로 답하지 않는다.
답 형식:
답: (한두 문장, 숫자 · 날짜 · 이름을 분명히. 날짜 조건이 있으면 오늘 기준으로 판단하고 근거 날짜를 함께)
근거: [페이지: 슬러그] (출처: 원본 파일명)  — 읽은 페이지 중 답의 근거가 된 것만
위키에 답이 없으면 '답: 위키에 없음' 이라고 쓰고 근거에는 '없음' 이라고 쓴다. 비슷한 값을 끌어다 짐작하지 않는다."""


def query(wiki, question, today):
    ans, tokens, trace = run_agent(wiki, QUERY_SYS.format(today=today, lim=PAGE_READ_LIMIT), question, TOOLS_RO, PAGE_READ_LIMIT + 4, PAGE_READ_LIMIT)
    return dict(answer=ans, tokens=tokens, pages_read=[s for n, s in trace if n == "read_page"])


# ── 점검 ─────────────────────────────────────────────────────────────────────
LINT_SYS = """너는 가나다식품(가상 회사) LLM 위키의 점검(lint) 담당이다. 위키 전체를 읽고 아래 네 가지를 찾는다. 위키 밖 지식은 쓰지 않는다.
1. 상충: 같은 항목에 서로 다른 값이 있는 곳(페이지 안, 페이지 사이). 어느 쪽이 맞을 가능성이 큰지와 그 근거(더 최신 · 1차 자료 · 계약서 > 메모)를 쓴다. 날짜 조건으로 둘 다 맞는 경우는 '날짜 조건'이라고 쓴다.
2. 낡음: 적용일이 지난 옛 값이 현재 값처럼 쓰인 곳.
3. 고아: 목차에 없거나 어느 페이지에서도 링크되지 않는 페이지.
4. 빠짐: 여러 페이지가 언급하지만 페이지가 없는 대상.
JSON 하나만 출력: {"conflicts":[{"topic":..,"pages":[..],"values":[..],"likely_right":..,"basis":..}],"stale":[{"page":..,"what":..}],"orphans":[..],"missing":[..]}"""


def lint(wiki, today):
    m, tokens = chat([{"role": "system", "content": LINT_SYS}, {"role": "user", "content": "오늘: %s\n\n[목차]\n%s\n\n[페이지 전부]\n%s" % (today, wiki.index(), wiki.all_text())}], temp=0.2)
    txt = m.content or ""
    j = re.search(r"\{.*\}", txt, re.S)
    try:
        data = json.loads(j.group(0)) if j else {}
    except Exception:
        data = {"_raw": txt}
    return dict(result=data, tokens=tokens)


# ── 비교 조건: 원본 통째 · 일반 RAG ─────────────────────────────────────────
BASE_SYS = """너는 가나다식품(가상 회사) 직원이 묻는 질문에 제공된 회사 자료만 보고 답하는 비서다. 오늘 날짜는 {today} 다.
답 형식:
답: (한두 문장, 숫자 · 날짜 · 이름을 분명히. 날짜 조건이 있으면 오늘 기준으로 판단)
근거: (출처: 원본 파일명) — 답의 근거가 된 자료만
자료에 답이 없으면 '답: 자료에 없음', 근거 '없음'. 짐작하지 않는다."""


def raw_files(include_ops=False):
    fs = sorted(glob.glob(os.path.join(RAW, "**", "*.*"), recursive=True))
    return [f for f in fs if include_ops or ("/ops/" not in f.replace("\\", "/"))]


def baseline_dump(question, today, files):
    ctx = "\n\n".join("<<파일 %s>>\n%s" % (os.path.relpath(f, RAW).replace("\\", "/"), read(f)) for f in files)
    m, tokens = chat([{"role": "system", "content": BASE_SYS.format(today=today)}, {"role": "user", "content": "[회사 자료 전부]\n%s\n\n[질문] %s" % (ctx, question)}])
    return dict(answer=m.content or "", tokens=tokens)


class RAG:
    """문단 · 표 청크(파일명 머리 포함) + 임베딩 · BM25 하이브리드. 캐시는 emb_cache.json."""
    def __init__(self, files, topk=8):
        self.topk = topk
        self.chunks = []
        for f in files:
            name = os.path.relpath(f, RAW).replace("\\", "/")
            t = read(f)
            parts = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
            buf = ""
            for p in parts:
                if p.startswith("|") and buf.startswith("|") and len(buf) < 1500:
                    buf += "\n" + p
                    continue
                if buf:
                    self.chunks.append("[%s]\n%s" % (name, buf))
                buf = p
                if buf.startswith("|") and len(buf) > 1500:      # 긴 표는 12줄씩
                    rows = buf.splitlines()
                    head = "\n".join(rows[:2])
                    for i in range(2, len(rows), 12):
                        self.chunks.append("[%s]\n%s\n%s" % (name, head, "\n".join(rows[i:i + 12])))
                    buf = ""
            if buf:
                self.chunks.append("[%s]\n%s" % (name, buf))
        cache = os.path.join(HERE, "emb_cache.json")
        c = json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else {}
        todo = [ch for ch in self.chunks if ch not in c]
        for i in range(0, len(todo), 64):
            r = client.embeddings.create(model=EMB, input=todo[i:i + 64])
            for ch, d in zip(todo[i:i + 64], r.data):
                c[ch] = d.embedding
        if todo:
            json.dump(c, open(cache, "w", encoding="utf-8"))
        self.vec = [c[ch] for ch in self.chunks]
        self.docs = [Counter(self.toks(ch)) for ch in self.chunks]
        self.avg = sum(sum(d.values()) for d in self.docs) / len(self.docs)
        self.df = Counter(t for d in self.docs for t in d)

    @staticmethod
    def toks(t):
        out = re.findall(r"[A-Za-z]+-?\d*|\d[\d,./-]*", t)
        for w in re.findall(r"[가-힣]+", t):
            out += [w[i:i + 2] for i in range(max(1, len(w) - 1))]
        return [o.upper() for o in out]

    def bm25(self, q, k1=1.5, b=0.75):
        qs, N, sc = self.toks(q), len(self.docs), []
        for d in self.docs:
            L, s = sum(d.values()), 0
            for t in qs:
                if t in d:
                    idf = math.log(1 + (N - self.df[t] + .5) / (self.df[t] + .5))
                    s += idf * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * L / self.avg))
            sc.append(s)
        return sc

    def search(self, q):
        qv = client.embeddings.create(model=EMB, input=[q]).data[0].embedding
        cos = lambda a, b: sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
        d = sorted(range(len(self.chunks)), key=lambda i: -cos(qv, self.vec[i]))
        sc = self.bm25(q); s = sorted(range(len(self.chunks)), key=lambda i: -sc[i])
        rrf = Counter()
        for rank, i in enumerate(d):
            rrf[i] += 1 / (61 + rank)
        for rank, i in enumerate(s):
            if sc[i] > 0:
                rrf[i] += 1 / (61 + rank)
        return [i for i, _ in rrf.most_common(self.topk)]

    def answer(self, question, today):
        ids = self.search(question)
        ctx = "\n\n".join(self.chunks[i] for i in ids)
        m, tokens = chat([{"role": "system", "content": BASE_SYS.format(today=today)}, {"role": "user", "content": "[검색된 자료]\n%s\n\n[질문] %s" % (ctx, question)}])
        return dict(answer=m.content or "", tokens=tokens, chunks=[self.chunks[i][:80] for i in ids])


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "selftest":
    import shutil, tempfile
    d = tempfile.mkdtemp(prefix="wiki_")
    w = Wiki(d)
    r = ingest(w, os.path.join(RAW, "suppliers", "한빛물류_요금표.md"), "2026-10-26")
    print("ingest:", r["pages_written"], r["tokens"], "토큰\n", r["report"])
    q = query(w, "제주로 냉동 택배 보내면 건당 얼마야?", "2026-10-26")
    print("query:", q["answer"], q["pages_read"])
    print("index:\n", w.index())
    shutil.rmtree(d, ignore_errors=True)
