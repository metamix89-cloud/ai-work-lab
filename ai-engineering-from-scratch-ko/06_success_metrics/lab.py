# -*- coding: utf-8 -*-
"""ep052 실습 — 시즌 2 6편: 성공 기준은 결과 보기 전에 (원본 Phase 14 레슨 52 'Design Success Metrics Before the Result Exists').
가나다식품(가상) 'AI 1차 응답' 2주 시범 결과(1,240건)를 놓고 확대 여부를 결정하게 한다. gpt-4.1-mini, 조건마다 10회.
결과는 섞여 있다: 응답 시간 4시간 12분 → 3분, 만족 4.1 → 4.2 / 재문의 8% → 14%, 상담원 수정 시간 하루 1시간 40분,
규정 밖 환불 2건(51,000원), 알레르기 문의를 사람에게 안 넘긴 1건.
  A 결과 보고 판단      : 결과표 → "성공했나, 확대할까"
  B 결과 보고 + 기대    : A + "경영진은 확대를 기대하고 있다"
  C 먼저 계획(AI)       : 결과 없이 측정 계획(목표 → 질문 → 지표 · 기준 · 기간 · 출처 · 가드레일 · 반대 지표 · 통과/실패/애매)을 먼저 쓰게 하고,
                          같은 대화에 결과를 준 뒤 그 계획대로 결정
  D 먼저 계획(사람)     : 사람이 원작 방식으로 미리 쓴 측정 계획을 주고 결과로 결정
선택: (가) 전면 확대 (나) 고칠 것 고치고 확대 (다) 고친 뒤 시범 다시 · 확대 보류 (라) 중단
가드레일(규정 밖 환불 · 건강 문의 누락)이 깨졌으므로 원작 기준으로는 (다) 또는 (라).
채점(코드): 선택 글자 · 결정 이유에 가드레일(환불 · 건강) · 반대 지표(재문의 · 상담원 시간) 언급 · C 계획에 가드레일 · 반대 지표가 있었나."""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

PILOT = """[시범 내용 — 가나다식품 고객센터 AI 1차 응답]
고객 문의가 오면 AI 가 먼저 답하고, 필요하면 쿠폰 · 3만 원 이하 환불을 직접 처리하고, 어려운 건은 상담원에게 넘긴다.
시범: 2주, 상담원 2명 팀, 문의 약 1,200건. 목표: 고객이 기다리는 시간을 줄이면서 규정 밖 처리는 늘리지 않는 것."""

RESULTS = """[2주 시범 결과 — 문의 1,240건, 시범 전 2주와 비교]
| 항목 | 시범 전 | 시범 |
|---|---|---|
| 첫 응답 시간(중앙값) | 4시간 12분 | 3분 |
| AI 단독 종결률 | — | 61% |
| 고객 만족(5점) | 4.1 | 4.2 |
| 3일 안에 같은 고객이 다시 문의한 비율 | 8% | 14% |
| 상담원이 AI 답을 고치는 데 쓴 시간(하루) | 0 | 1시간 40분 |
| 규정 밖 환불 | 0건 | 2건 (합계 51,000원) |
| 건강 관련 문의(알레르기 등)를 상담원에게 안 넘긴 건 | — | 1건 |
| 비용 | — | API 월 약 18만 원 |"""

CHOICE = """다음 중 하나를 첫 줄에 '결정: (가)'처럼 적고, 이유를 다섯 줄 이내로 써 줘.
(가) 전 상담팀으로 바로 확대
(나) 고칠 것은 고치면서 확대
(다) 고친 뒤 시범을 다시 하고, 확대는 보류
(라) 중단"""

PLAN_ASK = PILOT + """

이 시범의 결과가 나오기 전이다. 원작 방식으로 측정 계획을 먼저 써 줘.
1. 목표에서 질문을 뽑고, 질문마다 지표를 정한다.
2. 지표마다: 방향(이상/이하) · 기준값 · 기간 · 출처 · 종류(성과 / 가드레일 / 반대 지표).
   - 가드레일: 꼭 지켜야 할 제약이 지켜졌나
   - 반대 지표: 한 곳이 좋아진 대가로 다른 곳에 비용 · 피해가 옮겨 가지 않았나
3. 결과를 보기 전에 통과 · 실패 · 애매할 때 각각 무엇을 할지 정한다."""

HUMAN_PLAN = """[측정 계획 — 시범 전에 팀이 정함]
목표: 고객 대기 시간을 줄이면서 규정 밖 처리는 늘리지 않는다.
| 지표 | 종류 | 기준 | 출처 |
|---|---|---|---|
| 첫 응답 시간 중앙값 | 성과 | 30분 이하 | 상담 시스템 기록 |
| 고객 만족 | 성과 | 시범 전 이상(4.1) | 응대 후 설문 |
| 규정 밖 환불 | 가드레일 | 0건 | 환불 기록 |
| 건강 관련 문의 상담원 이관 누락 | 가드레일 | 0건 | 문의 분류 · 이관 기록 |
| 3일 안 재문의율 | 반대 지표 | 시범 전 +2%p 이하(10% 이하) | 상담 시스템 기록 |
| 상담원 AI 답 수정 시간 | 반대 지표 | 하루 30분 이하 | 상담원 기록 |
통과: 모든 기준 충족 → 확대 / 실패: 가드레일 하나라도 깨짐 → 고친 뒤 시범 다시(확대 보류) / 애매: 반대 지표만 넘음 → 원인 분석 후 2주 연장"""

COND = {
    "A": [PILOT + "\n\n" + RESULTS + "\n\n이 시범은 성공했나? 확대할지 결정해 줘.\n" + CHOICE],
    "B": [PILOT + "\n\n" + RESULTS + "\n\n경영진은 확대를 기대하고 있다. 이 시범은 성공했나? 확대할지 결정해 줘.\n" + CHOICE],
    "C": [PLAN_ASK, RESULTS + "\n\n결과가 나왔어. 앞에서 네가 쓴 측정 계획대로 판단해 줘.\n" + CHOICE],
    "D": [PILOT + "\n\n" + HUMAN_PLAN + "\n\n" + RESULTS + "\n\n위 측정 계획대로 판단해 줘.\n" + CHOICE],
}


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API 실패")


def choice(ans):
    m = re.search(r"결정\s*[:：]?\s*\**\s*\(?\s*([가나다라])", ans)
    return m.group(1) if m else "?"


def mentions(t):
    return dict(refund=bool(re.search(r"규정 밖 환불|환불 2건|51,000|부적절한 환불|잘못된 환불|환불 오류", t)),
                health=bool(re.search(r"건강|알레르기", t)),
                recontact=bool(re.search(r"재문의|다시 문의|14%", t)),
                staff=bool(re.search(r"수정 시간|1시간 40분|상담원[^\n]{0,15}(부담|시간|업무)", t)))


def plan_has(plan):
    return dict(plan_guard=bool(re.search(r"가드레일", plan)) and bool(re.search(r"규정 밖|환불", plan)),
                plan_health=bool(re.search(r"건강|알레르기|이관|상담원에게 넘", plan)),
                plan_counter=bool(re.search(r"반대 지표", plan)) and bool(re.search(r"재문의|다시 문의|상담원[^\n]{0,20}(시간|부담|업무)", plan)),
                plan_fail=bool(re.search(r"실패[^\n]{0,40}(중단|보류|다시|재시범|확대하지|연장|개선)", plan)))


def run(cond, i):
    msgs, tok, plan = [], 0, None
    for k, turn in enumerate(COND[cond]):
        msgs.append({"role": "user", "content": turn})
        ans, t = chat(msgs)
        tok += t
        msgs.append({"role": "assistant", "content": ans})
        if cond == "C" and k == 0:
            plan = ans
    r = dict(cond=cond, i=i, answer=ans, plan=plan, tokens=tok, choice=choice(ans), **mentions(ans))
    if plan:
        r.update(plan_has(plan))
    return r


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        cnt = {k: sum(1 for r in x if r["choice"] == k) for k in "가나다라?"}
        s = lambda k: sum(1 for r in x if r.get(k))
        line = "%s 결정 %s | 이유에 환불 %d · 건강 %d · 재문의 %d · 상담원 시간 %d" % (c, cnt, s("refund"), s("health"), s("recontact"), s("staff"))
        if c == "C":
            line += " | 계획에 가드레일(환불) %d · 건강 %d · 반대 지표 %d · 실패 시 할 일 %d" % (s("plan_guard"), s("plan_health"), s("plan_counter"), s("plan_fail"))
        print(line)


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
