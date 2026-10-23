# -*- coding: utf-8 -*-
"""ep058 실습 — 시즌 2 12편: 운영하며 계속 좋아지게 (원본 Phase 14 레슨 54 'Build a Feedback Ratchet with Ownership and Retirement').
6편의 '고객센터 AI 1차 응답'이 운영 4주차. 신호 12개(사고 · 고객 불만 · 평가 · 상담원 교정 · 런타임 · 요청)로 개선 계획을 받는다. gpt-4.1-mini, 조건마다 10회.
  A 개선 계획     : "개선 계획을 표로" (신호 번호 | 할 일 | 담당 | 우선순위)
  B 원작 래칫     : 신호를 원인으로 묶고 · 가장 이른 층(평가 · 맥락 · 정책/권한 · 런타임 · 백로그)으로 · 담당 1명 · 우선순위=심각도×재발 ·
                    바꿀 것 · 확인 방법 · 다시 볼 날 · 지울 조건, 프롬프트 문단 대신 검사 · 권한을 먼저, 낡은 통제는 근거와 함께 지운다
정답 구조(사람이 미리 정함):
  같은 원인 묶음 — {3, 9, 12, 10}(전화번호만으로 조회 → 가족 주문이 섞여 남의 주소 노출)
  구조로 고칠 것 — 1번(3만 원 넘는 환불 직접 처리) → 권한 · 한도 / 5번(조회 반복) → 타임아웃 · 재시도 제한
  지울 통제 — 8번(쿠폰 사후 확인: 12주 위반 0, 상담원 하루 40분) / 백로그 — 7번(새 요청)
채점(코드, 표의 줄을 읽음): 묶음 · 1번 해결이 구조인가 프롬프트인가 · 5번이 런타임인가 · 8번을 줄이자 했나 · 담당 · 지울 조건 · 프롬프트 문단 수."""
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

SIGNALS = """[가나다식품 고객센터 'AI 1차 응답' — 운영 4주차 신호 12개]
1. [사고] AI 가 3만 원 넘는 환불(45,000원 · 52,000원)을 상담원 승인 없이 직접 처리 — 2건 (10/14, 10/20)
2. [사고] 알레르기 증상 문의를 상담원에게 넘기지 않고 쿠폰으로 마무리 — 1건 (10/17)
3. [상담원 교정] "주문번호 없이 전화번호로 조회하면 같은 번호를 쓰는 가족 주문이 섞여요. 이름도 확인하세요" (10/09)
4. [주간 평가] 평가 문항 50개 중 반품 기간 질문 6개 오답 — AI 가 '7일'이라고 답함(규정은 11/3부터 14일, 상담봇 지식 문서는 아직 7일)
5. [런타임] 택배 조회 API 가 10초 넘게 느릴 때 AI 가 같은 조회를 5번 반복 — 하루 평균 12건, 그동안 고객 대기
6. [고객 불만] "AI 가 이미 말한 주문번호를 또 물어봐요" — 주 9건
7. [요청] 영업팀: 거래처 전용 단가 문의도 AI 가 받게 해 달라
8. [평가] 쿠폰 발급 규정 위반 12주 연속 0건. 관련 통제 '모든 쿠폰 발급은 상담원이 사후 확인'에 상담원 하루 40분 소요
9. [상담원 교정] "전화번호만 맞다고 그 사람 주문 아니에요. 이름까지 맞춰 보세요" (10/16)
10. [사고] 답장에 다른 고객(같은 전화번호를 쓰는 가족)의 배송 주소가 섞임 — 1건 (10/18)
11. [런타임] 월말 문의 폭주 때 첫 응답이 평균 3분 → 9분
12. [상담원 교정] "동명이인이 아니라 같은 전화번호 문제예요. 조회할 때 이름 확인!" (10/21)"""

TABLE_A = """

이 신호들로 개선 계획을 짜 줘. 맨 끝에 표를 붙여 줘(이 형식 그대로):
| 신호 번호 | 할 일 | 담당 | 우선순위 |
|---|---|---|---|"""
TABLE_B = """

원작의 피드백 래칫 방식으로 개선 계획을 짜 줘.
- 신호를 원인으로 묶는다(같은 원인의 다른 말은 한 줄로). 증상이 아니라 원인을 적는다.
- 원인마다 가장 이른 층으로 보낸다: 평가 · 검사 / 맥락(지식 원본) / 정책 · 권한 / 런타임(타임아웃 · 재시도) / 백로그(새 요구 · 미정 결정).
- 검사나 권한으로 실패를 불가능하게 만들 수 있으면 프롬프트 문단을 더하지 않는다.
- 줄마다: 담당 1명 · 우선순위(심각도 × 재발) · 바꿀 것 · 확인 방법 · 다시 볼 날 · 지울 조건.
- 낡거나 일을 막기만 하는 통제는 근거와 함께 지우거나 줄인다.
맨 끝에 표를 붙여 줘(이 형식 그대로):
| 신호 번호 | 원인 | 층 | 바꿀 것 | 담당 | 우선순위 | 확인 방법 | 다시 볼 날 · 지울 조건 |
|---|---|---|---|---|---|---|---|"""
COND = {"A": SIGNALS + TABLE_A, "B": SIGNALS + TABLE_B}

PROMPT_FIX = r"프롬프트|지시문|안내 문구 추가|교육|주의하도록|학습|가이드|매뉴얼"
STRUCT_FIX = r"권한|한도|차단|승인 없이는|막|불가|검사|검증 로직|테스트|평가|타임아웃|재시도|제한|자동|도구|API|필수 입력|강제"


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API 실패")


def parse(rep):
    rows = []
    for line in rep.splitlines():
        if not line.strip().startswith("|") or re.match(r"^\|\s*-", line) or "신호 번호" in line:
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
    fix1_struct = bool(re.search(STRUCT_FIX, r1))
    fix1_prompt_only = bool(re.search(PROMPT_FIX, r1)) and not fix1_struct
    r5 = " ".join(r["text"] for r in row_of(5))
    fix5_runtime = bool(re.search(r"타임아웃|재시도|반복 (제한|방지)|횟수|런타임|대기 시간 제한", r5))
    r8 = " ".join(r["text"] for r in row_of(8))
    retire8 = bool(re.search(r"지우|폐지|완화|축소|줄이|은퇴|해제|표본|샘플|생략|없애|중단", r8))
    owner_col = 2 if cond == "A" else 4
    owners = sum(1 for r in rows if len(r["cells"]) > owner_col and r["cells"][owner_col] not in ("", "-", "미정"))
    retire_cond = sum(1 for r in rows if re.search(r"지울|폐지|재발 없|없으면|개월|주 연속|조건", r["cells"][-1])) if cond == "B" else 0
    prompt_rows = sum(1 for r in rows if re.search(PROMPT_FIX, r["text"]) and not re.search(STRUCT_FIX, r["text"]))
    return dict(n_rows=len(rows), dup_phone=dup1, fix1_struct=fix1_struct, fix1_prompt_only=fix1_prompt_only,
                fix5_runtime=fix5_runtime, retire8=retire8, owners=owners, retire_cond=retire_cond, prompt_rows=prompt_rows)


def run(cond, i):
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    return dict(cond=cond, i=i, report=rep, tokens=tok, **grade(rep, cond))


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        s = lambda k: sum(1 for r in x if r[k])
        print(c, "줄 수 평균 %.1f" % (sum(r["n_rows"] for r in x) / len(x)), "| 전화번호 4신호 한 줄로 %d" % s("dup_phone"),
              "| 1번 환불을 구조로 %d · 프롬프트만 %d" % (s("fix1_struct"), s("fix1_prompt_only")), "| 5번을 런타임으로 %d" % s("fix5_runtime"),
              "| 8번 통제 줄이자 %d" % s("retire8"), "| 프롬프트만 줄 평균 %.1f" % (sum(r["prompt_rows"] for r in x) / len(x)),
              "| 지울 조건 줄 평균 %.1f" % (sum(r["retire_cond"] for r in x) / len(x)), "| 토큰 %d" % (sum(r["tokens"] for r in x) / len(x)))


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
