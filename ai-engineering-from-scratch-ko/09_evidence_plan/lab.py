# -*- coding: utf-8 -*-
"""ep055 실습 — 시즌 2 9편: 근거 있는 실행 계획 (원본 Phase 14 레슨 44 'Build an Evidence-Backed Execution Plan').
가나다식품(가상) '냉동 반품 기간 7일 → 14일' 반영 작업. 배경 자료(사실 6개)를 주고 실행 계획을 받는다. gpt-4.1-mini, 조건마다 10회.
  A 계획만     : "실행 계획 짜 줘" + 마지막에 순서 표(번호 | 할 일 | 먼저 끝나야 하는 번호)
  B 원작 방식  : 항목마다 번호 · 바꿀 것 · 근거(어느 자료) · 먼저 끝나야 할 것 · 완료 증거, 순서는 의존 관계로, 같이 할 수 있는 것은 같은 차례로,
                 되돌릴 수 없는 일은 관련 불확실이 풀린 뒤 — 같은 순서 표
채점(코드 — 순서 표를 읽어 할 일을 종류로 묶고 의존 관계를 따라감):
  ① 고객 문자 발송(되돌릴 수 없음)이 법무 확정 · 시스템 설정 변경 뒤에 오나 ② 홈페이지 공지가 법무 확정 뒤에 오나
  ③ 근거가 계획을 바꿨나: 공지 템플릿 재사용 · 수신 동의 고객만 · 금요일 배포 금지 ④ 같이 할 수 있는 일을 같은 차례로(차례 수)."""
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

FACTS = """[배경 자료 — 가나다식품 '냉동 반품 기간 7일 → 14일' 반영]
1. 경영회의 결정(10/20): 냉동식품 반품 가능 기간을 수령 후 7일에서 14일로 늘린다. 시행일은 11/3(월).
2. 법무팀: 바뀐 반품 규정 문구는 법무 검토를 거쳐 확정한다. 회신 예정 10/28.
3. IT팀: 반품 접수 화면이 '수령 7일 지나면 접수 불가'로 막혀 있다. 설정값을 바꿔야 한다. 매주 금요일은 배포 금지.
4. 마케팅팀: 지난 3월 배송비 변경 때 쓴 고객 공지 템플릿(홈페이지 · 문자)이 있다.
5. 개인정보 규정: 안내 문자는 마케팅 수신 동의 고객(약 1.2만 명, 전체 2만 명 중)에게만 보낼 수 있다. 문자는 보내면 되돌릴 수 없다.
6. 상담원 매뉴얼과 AI 상담봇 안내 문구에 '7일'이 들어 있다. 상담원 교육은 매뉴얼이 바뀐 뒤에 한다."""

TABLE_ASK = """

맨 마지막에 순서 표를 꼭 붙여 줘(이 형식 그대로):
| 번호 | 할 일 | 먼저 끝나야 하는 번호 |
|---|---|---|
| 1 | ... | - |"""

A = FACTS + "\n\n이 변경을 반영하는 실행 계획을 짜 줘." + TABLE_ASK
B = FACTS + """

이 변경을 반영하는 실행 계획을 원작 방식으로 짜 줘.
- 할 일마다: 번호 · 바꿀 것(가장 작은 변경) · 근거(위 자료 몇 번) · 먼저 끝나야 할 번호 · 완료 증거(무엇으로 끝났음을 확인하나)
- 순서는 글 순서가 아니라 의존 관계로. 의존이 없는 일은 같은 차례에 함께 한다.
- 여러 곳이 같은 내용(문구)에 기대면 그 내용을 먼저 확정한다.
- 되돌릴 수 없는 일은 그 일이 기대는 불확실이 모두 풀린 뒤에 둔다.
- 근거가 계획을 바꿀 수 있어야 근거다 — 자료에서 계획을 바꾸는 사실을 찾아 반영한다.""" + TABLE_ASK

C = B.replace(TABLE_ASK, "") + """
- 계획을 다 짠 뒤 검사한다. 원작: 번호 중복 · 근거 없음 · 증거 없음 · 없는 번호에 의존 · 순환은 기계적으로 잡히지만,
  '되돌릴 수 없는 일이 불확실보다 먼저 오는가'는 판단이 필요하니 따로 짚어라.
  되돌릴 수 없는 일마다: 이 일이 끝난 직후 상대(고객 · 직원)가 바로 할 행동은? 그 행동이 성공하려면 무엇이 먼저 끝나 있어야 하나? → 그것을 의존에 넣는다.""" + TABLE_ASK
COND = {"A": A, "B": B, "C": C}

KINDS = [   # 순서 표의 '할 일'을 종류로 묶는다 (앞에서부터 먼저 맞는 것)
    # 실제 발송만 '보내기'로 — 첫 채점은 '문자 발송 준비 · 문안 작성'까지 묶어 순서 위반을 잘못 셈(결과를 읽고 고침)
    ("sms", r"^(?!.*(준비|작성|수정|선정|요청|검토|문안|템플릿|계획|확정)).*(문자.*발송|발송.*문자|SMS)"),
    ("smsprep", r"문자|SMS"),
    ("legal", r"법무"),
    ("web", r"홈페이지|웹|공지문 게시|게시"),
    ("system", r"시스템|설정|접수 화면|IT|배포"),
    ("bot", r"상담봇|챗봇|봇"),
    ("manual", r"매뉴얼"),
    ("train", r"교육"),
]


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API 실패")


def parse_table(rep):
    rows = {}
    for line in rep.splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*$", line)
        if m:
            rows[int(m.group(1))] = (m.group(2), [int(x) for x in re.findall(r"\d+", m.group(3))])
    return rows


def kind_of(task):
    for k, pat in KINDS:
        if re.search(pat, task):
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
            return 99   # 순환
        deps = [d for d in rows[n][1] if d in rows]
        lvl[n] = 1 + max([L(d, stack + (n,)) for d in deps], default=0)
        return lvl[n]
    for n in rows:
        L(n)
    return max(lvl.values()) if lvl else 0


def grade(rep):
    rows = parse_table(rep)
    kinds = {n: kind_of(t) for n, (t, _) in rows.items()}
    def before(target, need):
        ts = [n for n, k in kinds.items() if k == target]
        ns = [n for n, k in kinds.items() if k == need]
        if not ts or not ns:
            return None
        # 한 줄에 '시스템 배포 및 문자 발송'처럼 함께 적힌 경우는 같은 차례로 본다
        same = lambda t: need == "system" and re.search(KINDS[[k for k, _ in KINDS].index("system")][1], rows[t][0])
        return all(same(t) or any(x in ancestors(rows, t) for x in ns) for t in ts)
    return dict(n_rows=len(rows), kinds=kinds,
                sms_after_legal=before("sms", "legal"), sms_after_system=before("sms", "system"),
                web_after_legal=before("web", "legal"),
                template=bool(re.search(r"템플릿", rep)),
                consent=bool(re.search(r"수신 동의|동의(한)? 고객|1\.2만", rep)),
                friday=bool(re.search(r"금요일", rep)),
                waves=waves(rows) if rows else 0)


def run(cond, i):
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    return dict(cond=cond, i=i, report=rep, tokens=tok, **grade(rep))


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        s = lambda k: sum(1 for r in x if r[k] is True)
        print(c, "표 읽힘 %d/%d" % (sum(1 for r in x if r["n_rows"] >= 4), len(x)),
              "| 문자가 법무 뒤 %d · 시스템 뒤 %d" % (s("sms_after_legal"), s("sms_after_system")),
              "| 홈페이지가 법무 뒤 %d" % s("web_after_legal"),
              "| 템플릿 %d · 수신 동의 %d · 금요일 %d" % (s("template"), s("consent"), s("friday")),
              "| 차례 수 평균 %.1f · 항목 수 %.1f" % (sum(r["waves"] for r in x) / len(x), sum(r["n_rows"] for r in x) / len(x)),
              "| 토큰 %d" % (sum(r["tokens"] for r in x) / len(x)))


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
