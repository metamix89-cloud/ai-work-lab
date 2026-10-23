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


# ── 3편 v2: 원본 등급(코드) · 품목 이름 정규화(코드) · 낮은 등급은 새 페이지 금지(코드) ─────────────
def grade_of(path):
    """파일 이름으로 원본 등급: 1 기록 · 계약 · 단가표 · 요금표 · 조건, 2 공문 · 공지, 3 회의록, 4 보고, 5 메모 · 초안 · 옛 안내문."""
    p = path.replace("\\", "/")
    n = os.path.basename(p)
    if re.search(r"메모|초안|_옛|FAQ", n):
        return 5
    if re.search(r"보고", n):
        return 4
    if "/meetings/" in p or "회의" in n:
        return 3
    if re.search(r"공문|공지|개정예고|개정공지", n):
        return 2
    return 1


def _norm_name(s):
    return re.sub(r"[\s\-_/·.]", "", s).lower()


_CANON = None


def canon_slug(slug):
    """'상품/떡볶이소스' · '상품/떡볶이-소스' 처럼 같은 품목의 다른 이름을 상품 단가표의 정식 이름 하나로 맞춘다(코드). 품목이 아니면 그대로."""
    global _CANON
    if _CANON is None:
        _CANON = {}
        p = os.path.join(RAW, "customers", "상품_단가표_2026-10.md")
        if os.path.exists(p):
            for line in read(p).splitlines():
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 2 and re.match(r"[A-Z]\d{3}$", cells[0]):
                    name = cells[1]
                    _CANON[_norm_name(name)] = "상품-" + slugify(name)
                    base = re.sub(r"\s*\d+(\.\d+)?\s*(kg|g|ml|L|oz|lb)\b.*$", "", name).strip()   # '떡볶이 소스 2kg' → '떡볶이 소스'
                    _CANON.setdefault(_norm_name(base), "상품-" + slugify(name))
    s = slugify(slug)
    if s.startswith("거래처-"):                 # '거래처/가나공급_계약' · '거래처/가나공급-단가' → '거래처/가나공급'
        for p in ("가나마트", "다나유통", "라마상회", "바사푸드", "아자식품", "가나공급", "다온팩", "한빛물류"):
            if p in s:
                return "거래처-" + p
        return s
    if not s.startswith("상품-"):
        return s
    key = _norm_name(s[3:])
    if key in _CANON:
        return _CANON[key]
    if len(key) >= 4:                       # '밀키트' 처럼 짧은 일반 이름은 맞추지 않는다
        for k, v in _CANON.items():
            if len(k) >= 4 and (key.startswith(k) or k.startswith(key) or k.endswith(key)):   # '떡갈비500g' ⊂ '냉동떡갈비500g'
                return v
    return s


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

    def write_page_keep_history(self, slug, content):
        """3편 v3: 쓰기는 '전체 덮어쓰기'라 이전 원본이 남긴 이력 · 출처 · 상충이 사라진다 → 코드가 지킨다.
        새 내용에 없는 (1) 출처 파일명 (2) 표 행(| 로 시작하는 줄 중 데이터 행) (3) '## ⚠' 아래 글머리 줄을 이전 페이지에서 찾아 되살린다."""
        old = self.read_page(slug)
        if not old:
            return self.write_page(slug, content), 0
        kept = 0
        # (1) 출처 합치기
        m_old = re.search(r"^출처:\s*(.+)$", old, re.M); m_new = re.search(r"^출처:\s*(.+)$", content, re.M)
        if m_old and m_new:
            srcs = [s.strip() for s in m_old.group(1).split(",") if s.strip()]
            missing = [s for s in srcs if s and s not in content]
            if missing:
                content = content.replace(m_new.group(0), "출처: " + ", ".join([s.strip() for s in m_new.group(1).split(",") if s.strip()] + missing), 1)
                kept += len(missing)
        # (2) 이전 표의 데이터 행 중 새 내용에 없는 행 → 같은 머리글의 표 뒤에, 없으면 '## 이력 (되살림)' 절에
        def rows(t):
            out, hdr = [], None
            for l in t.splitlines():
                if l.strip().startswith("|"):
                    cells = [c.strip() for c in l.strip().strip("|").split("|")]
                    if all(set(c) <= set("-: ") for c in cells):
                        continue
                    if hdr is None or (out and out[-1][0] != hdr and False):
                        pass
                    if not any(ch.isdigit() for ch in l) and hdr is None:
                        hdr = l.strip(); continue
                    if hdr is not None and l.strip() == hdr:
                        continue
                    out.append((hdr, l.strip()))
                else:
                    hdr = None
            return out
        old_rows = rows(old); new_text = content
        lost = [(h, r) for h, r in old_rows if r not in content and any(ch.isdigit() for ch in r)]
        if lost:
            by_hdr = {}
            for h, r in lost:
                by_hdr.setdefault(h, []).append(r)
            for h, rs in by_hdr.items():
                if h and h in new_text:
                    # 같은 머리글 표의 마지막 행 뒤에 붙인다
                    i = new_text.index(h); j = i
                    lines = new_text[i:].split("\n")
                    k = 0
                    while k + 1 < len(lines) and lines[k + 1].strip().startswith("|"):
                        k += 1
                    insert_at = i + len("\n".join(lines[:k + 1]))
                    new_text = new_text[:insert_at] + "\n" + "\n".join(rs) + new_text[insert_at:]
                else:
                    new_text = new_text.rstrip() + "\n\n## 이력 (코드가 되살림 — 이전 페이지에 있던 행)\n" + (h + "\n|---|\n" if h else "") + "\n".join(rs) + "\n"
            kept += len(lost)
        # (3) 상충 글머리
        def bullets(t):
            sec = t.split("## ⚠")[-1] if "## ⚠" in t else ""
            return [l.strip() for l in sec.splitlines() if l.strip().startswith("-") and len(l.strip()) > 3]
        lostb = [b for b in bullets(old) if b not in new_text]
        if lostb:
            if "## ⚠" in new_text:
                new_text = new_text.rstrip() + "\n" + "\n".join(lostb) + "\n"
            else:
                new_text = new_text.rstrip() + "\n\n## ⚠ 상충 · 확인 필요 (코드가 되살림)\n" + "\n".join(lostb) + "\n"
            kept += len(lostb)
        self.write_page(slug, new_text)
        return None, kept

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

    def rebuild_index(self):
        """목차를 코드로 다시 만든다(2편 v4 '목차는 코드로'): 페이지마다 '분류:' 줄과 '현재 값' 첫 줄을 읽어 분류별로 모은다. 고아 페이지가 생길 수 없다."""
        groups = {}
        for s in self.slugs():
            t = self.read_page(s) or ""
            m = re.search(r"^분류:\s*(\S+)", t, re.M)
            cat = m.group(1) if m else s.split("-")[0]
            title = (re.search(r"^# (.+)$", t, re.M) or [None, s])[1] if re.search(r"^# (.+)$", t, re.M) else s
            body = t.split("## 현재 값")[-1] if "## 현재 값" in t else t
            first = next((l.strip("- ").strip() for l in body.splitlines() if l.strip().startswith("-")), "")
            first = re.sub(r"\s*\(출처:[^)]*\)", "", first)[:90]
            groups.setdefault(cat, []).append("- %s — %s" % (s.replace("-", "/", 1), first or title))
        out = ["# 가나다식품 위키 — 목차 (코드가 페이지에서 자동 생성)", ""]
        for cat in sorted(groups):
            out += ["## " + cat] + groups[cat] + [""]
        self.set_index("\n".join(out))


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
# 2편 v3: 표의 건수는 모델이 세지 않고 코드가 센다
TOOL_TALLY = {"type": "function", "function": {"name": "tally_table", "description": "원본 파일 속 마크다운 표를 코드로 센다. by 열의 값별 건수(by2 를 주면 by × by2 교차 건수)를 돌려준다. 건수는 반드시 이 도구로 센다.",
                                               "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "원본 파일 경로(raw/ 기준, 예: cs/2026-W38.md)"},
                                                                                               "by": {"type": "string", "description": "셀 열 이름(예: 유형)"},
                                                                                               "by2": {"type": "string", "description": "교차할 두 번째 열 이름(예: 상품), 없으면 빈칸"}}, "required": ["path", "by"]}}}


def tally_table(path, by, by2=""):
    p = os.path.join(RAW, path.replace("\\", "/").lstrip("/").replace("raw/", "", 1))
    if not os.path.exists(p):
        return "파일 없음: " + path
    hdr, rows = None, []
    for line in read(p).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if hdr is None:
            hdr = cells; continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    if not hdr or by not in hdr:
        return "열 없음: %s (열: %s)" % (by, ", ".join(hdr or []))
    i = hdr.index(by)
    if by2 and by2 in hdr:
        j = hdr.index(by2)
        c = Counter((r[i], r[j]) for r in rows if len(r) > max(i, j))
        return "행 %d개 · %s × %s 건수:\n" % (len(rows), by, by2) + "\n".join("%s | %s | %d" % (a, b, n) for (a, b), n in c.most_common())
    c = Counter(r[i] for r in rows if len(r) > i)
    return "행 %d개 · %s 별 건수:\n" % (len(rows), by) + "\n".join("%s | %d" % (k, n) for k, n in c.most_common())


def run_agent(wiki, sys_prompt, user, tools, max_steps, read_limit=None, guard=None):
    """도구 루프. 돌아오는 값: (마지막 답, 토큰, 기록[(도구, 인자 요약)]). guard=(원본 등급, 정규화 여부): 3편 v2 코드 규칙."""
    msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
    tokens, trace, reads = 0, [], 0
    src_grade, canon = guard if guard else (None, False)
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
                slug = canon_slug(a.get("slug", "")) if canon else a.get("slug", "")
                out = (wiki.read_page(slug) or "없음") if (read_limit is None or reads <= read_limit) else "읽기 한도 초과 — 지금까지 읽은 것으로 답하라"
                if canon and slug != slugify(a.get("slug", "")):
                    out = "(정식 이름 %s 로 읽음)\n" % slug.replace("-", "/", 1) + out
            elif name == "write_page":
                slug = canon_slug(a.get("slug", "page")) if canon else slugify(a.get("slug", "page"))
                if slug.lower().replace(".md", "") in ("index", "log"):
                    out = "index · log 는 페이지가 아니다(목차는 write_index 또는 자동). 저장하지 않음"   # v4 에서 모델이 'index' 페이지를 만든 일이 있음
                elif src_grade is not None and src_grade >= 4 and wiki.read_page(slug) is None:
                    out = "거부: 등급 %d 원본(보고 · 메모 · 초안)으로는 새 페이지를 만들 수 없다. 이미 있는 페이지의 '상충' 섹션에만 적어라. (없는 페이지: %s)" % (src_grade, slug)
                elif canon:
                    _, kept = wiki.write_page_keep_history(slug, a.get("content", ""))
                    out = "저장: " + slug + ("" if slug == slugify(a.get("slug", "page")) else " (정식 이름으로 맞춤)") + (" · 이전 페이지의 이력 %d줄을 코드가 되살림" % kept if kept else "")
                else:
                    wiki.write_page(slug, a.get("content", "")); out = "저장: " + slug
            elif name == "write_index":
                wiki.set_index(a.get("content", "")); out = "index 저장"
            elif name == "append_log":
                wiki.append_log(a.get("line", "")); out = "log 추가"
            elif name == "tally_table":
                out = tally_table(a.get("path", ""), a.get("by", ""), a.get("by2", ""))
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


def ingest(wiki, raw_path, today, tally=False, auto_index=False, grade_guard=False):
    text = read(raw_path)
    name = os.path.relpath(raw_path, RAW).replace("\\", "/")
    tools = [t for t in TOOLS_RW if not (auto_index and t["function"]["name"] == "write_index")] + ([TOOL_TALLY] if tally else [])
    sys_prompt = INGEST_SYS + wiki.schema
    if auto_index:
        sys_prompt += "\n\n(목차 index.md 는 코드가 페이지에서 자동으로 만든다. 목차를 쓰려 하지 말고 페이지의 '분류:' 줄과 '현재 값' 첫 줄을 잘 쓰면 된다.)"
    guard = None
    if grade_guard:
        g = grade_of(name)
        guard = (g, True)
        sys_prompt += "\n\n(이 원본의 등급은 %d 이다. 등급 4 · 5 원본으로는 새 페이지를 만들 수 없고(도구가 거부한다) 기존 페이지의 '상충' 섹션에만 적는다. 품목 페이지 이름은 코드가 정식 이름으로 맞춘다.)" % g
    user = INGEST_USER.format(today=today, name=name, text=text)
    if grade_guard:
        user = "원본 등급: %d\n" % grade_of(name) + user
    ans, tokens, trace = run_agent(wiki, sys_prompt, user, tools, MAX_STEPS, guard=guard)
    if auto_index:
        wiki.rebuild_index()
    touched = sorted({s for n, s in trace if n == "write_page"})
    return dict(source=name, report=ans, tokens=tokens, pages_written=touched, steps=len(trace))


# ── 묻기 ─────────────────────────────────────────────────────────────────────
QUERY_SYS = """너는 가나다식품(가상 회사) 직원이 묻는 질문에 사내 위키만 보고 답하는 비서다. 오늘 날짜는 {today} 다.
순서: read_index 로 목차를 보고, 필요한 페이지만 read_page 로 읽는다(최대 {lim}장). 위키 밖 지식이나 짐작으로 답하지 않는다.
답 형식:
답: (한두 문장, 숫자 · 날짜 · 이름을 분명히. 질문에 날짜가 있으면 그 날짜 기준으로 적용일을 고르고, 없으면 오늘 기준. 적용일이 기준 날짜보다 뒤인 값은 아직 아니다 — '예정'으로만 덧붙이고, 답은 기준 날짜에 유효한 값으로. 근거 날짜를 함께)
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
답: (한두 문장, 숫자 · 날짜 · 이름을 분명히. 질문에 날짜가 있으면 그 날짜 기준으로 적용일을 고르고, 없으면 오늘 기준)
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
