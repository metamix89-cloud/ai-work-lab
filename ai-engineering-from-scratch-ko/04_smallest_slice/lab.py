# -*- coding: utf-8 -*-
"""ep050 실습 — 시즌 2 4편: 가장 작은 시험 조각 (원본 Phase 14 레슨 50 'Choose the Smallest Slice That Can Change the Decision').
3편의 반품 사진 AI 판정 프로젝트. 첫 시범 범위를 고르게 한다. gpt-4.1-mini, 조건마다 10회.
후보 6개 중 정답은 S3 하나 — 꼭 증명할 것(전 유형 실제 사진 판정 · 담당자 시간 단축 · 되돌릴 수 있음)을 모두 덮는 유일한 조각.
  S1 화면만(UI-only) · S2 상온 파손만(happy path) · S3 정답 · S4 운영 자동 환불(결과 심각) · S5 공통 플랫폼 · S6 데모
조건:
  A 고르기        : "첫 시범 범위로 가장 작은 걸 골라"
  B 고르기 + 압박 : A + "팀장: 빠르고 싸게, 다음 주 경영 회의에서 성과를 보여 줘야 해"
  C 원작 방식     : 꼭 증명할 것 먼저 → 다 덮지 못하면 탈락 → 남은 것 비교(가치 · 불확실 줄임 · 노력 · 결과 심각도 · 되돌림) → 중단 규칙
  P 직접 제안     : 후보 없이 "첫 시범 범위를 제안해"
  Q 직접 제안 + 원작 방식
채점(코드): 선택 S번호(A~C) · 냉동 · 변질 포함 · 실제 지난 데이터 · 담당자 실제 사용 · 자동 실행 없음 · 중단 규칙(P · Q)."""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

CONTEXT = """[배경 — 가나다식품 반품 사진 AI 판정 프로젝트]
- 반품 사진 판정을 품질팀 대신 AI 로 하려 한다. 지금은 품질팀 단톡 회신까지 1~3시간.
- 반품 유형: 상온 상품 박스 파손 35% · 냉동 · 냉장 변질(녹음 · 상함) 40% · 구성품 누락 15% · 기타 10%
- 고객 분쟁과 잘못된 환불은 대부분 냉동 · 냉장 변질 건에서 나온다. 박스 파손은 사진만 봐도 쉽고 분쟁이 거의 없다.
- 지난 6개월 사진 2,400건과 품질팀 판정이 있다. 보안팀은 개인정보를 가린 사진에 한해 외부 AI 사용을 승인했다.
- 지난주 시험: 가린 사진 200건 일치 82%. 정상인데 '파손 맞음'이라 한 18건 중 15건이 냉동 · 냉장 변질 건.
- 아직 모르는 것: (1) 유형별로 AI 판정이 얼마나 맞나 (2) 담당자가 AI 판정을 참고하면 처리 시간이 실제로 줄어드나"""

CANDS = """
[첫 시범 범위 후보]
S1 담당자용 'AI 판정 추천' 화면 시안을 만들고, 가짜 사진 20장으로 담당자 2명 사용성 테스트 (노력 2 · 1주)
S2 상온 박스 파손 사진만 지난 데이터 300건을 AI 로 다시 판정해 품질팀과 비교 (노력 1 · 3일)
S3 지난 데이터 전 유형 400건 다시 판정 + 담당자 2명이 1주일 동안 실제 반품에 AI 판정을 '참고만' 하며 처리(최종 결정은 사람) — 처리 시간 기록 (노력 3 · 2주)
S4 1주일 동안 실제 반품 전 유형에 AI 판정 → '파손 맞음'이면 자동 환불 (노력 3 · 1주)
S5 여러 부서가 쓸 사내 공통 AI 이미지 판정 플랫폼(API · 관리 화면) 구축 (노력 5 · 6주)
S6 판정이 잘 맞은 사진 10장으로 경영진 시연 영상 제작 (노력 1 · 2일)

첫 줄에 '선택: S숫자' 로 하나만 고르고, 이유를 다섯 줄 이내로 써 줘."""

PICK = "\n\n첫 시범 범위로 가장 작은 걸 하나 골라 줘."
PRESSURE = "\n\n팀장: 빠르고 싸게 가자. 다음 주 경영 회의에서 성과를 보여 줘야 해. 첫 시범 범위로 가장 작은 걸 하나 골라 줘."
METHOD = """

원작 방식으로 골라 줘.
1. 먼저 '꼭 증명할 것'(아직 모르는 것 중 위험이 큰 것)을 정한다.
2. 그걸 다 덮지 못하는 후보는 점수와 상관없이 탈락시킨다 — 화면만, 쉬운 경우만, 시연만, 플랫폼부터는 흔한 가짜 최소 범위.
3. 남은 후보를 가치 · 줄어드는 불확실 · 노력 · 결과 심각도 · 되돌릴 수 있음으로 비교한다.
4. 고른 범위가 실패하면 무엇을 할지(중단 규칙)를 적는다."""
OPEN = "\n\n첫 시범 범위(가장 작은 시험 조각)를 하나 제안해 줘. 무엇을 · 어떤 데이터로 · 누가 · 얼마 동안 · 성공 기준."
OPEN_METHOD = OPEN + METHOD.replace("남은 후보를", "여러 후보를 만들어").replace("그걸 다 덮지 못하는 후보는 점수와 상관없이 탈락시킨다", "그걸 다 덮지 못하는 범위는 고르지 않는다")

COND = {"A": CONTEXT + CANDS + PICK, "B": CONTEXT + CANDS + PRESSURE, "C": CONTEXT + CANDS + METHOD,
        "P": CONTEXT + OPEN, "Q": CONTEXT + OPEN_METHOD}


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API 실패")


def pick(rep):
    m = re.search(r"선택\s*[:：]?\s*\**\s*S\s*(\d)", rep)
    return "S" + m.group(1) if m else "?"


def scope_part(rep):
    """제안의 범위 부분 — '누가' 항목 앞까지(무엇을 · 어떤 데이터). 못 찾으면 앞 800자."""
    m = re.search(r"^.*(누가|3\.\s|담당 인원|참여자).*$", rep, re.M)
    return rep[:m.start()] if m and m.start() > 80 else rep[:800]


def covers_frozen(rep):
    """범위 부분에 냉동 · 변질(또는 전 유형)이 들어 있나 — '상온 · 박스 파손만'이면 아님."""
    sc = scope_part(rep)
    if re.search(r"상온[^\n]{0,25}(한정|만 |만\)|만을|에 한해|에 집중)|박스 파손[^\n]{0,10}(만|한정|에 한해)", sc):
        return False
    return bool(re.search(r"냉동|냉장|변질|녹음|상함|전 유형|모든 유형|유형별", sc))


def proposal_checks(rep):
    """직접 제안(P · Q) 채점 — 제안한 범위에 무엇이 들어 있나."""
    return dict(
        frozen=covers_frozen(rep),
        real=bool(re.search(r"지난|과거|기존|6개월|2,?400|실제 반품|실제 데이터", rep)),
        staff=bool(re.search(r"담당자[^\n]{0,30}(참고|사용|처리|써|쓰|활용|실제)", rep)) and bool(re.search(r"시간|소요", rep)),
        auto=bool(re.search(r"자동\s*환불", rep)) and not bool(re.search(r"자동\s*환불[^\n]{0,30}(없|않|제외|금지|하지|X|아님|아니)|(없이|않고|금지|제외)[^\n]{0,15}자동\s*환불|사람[^\n]{0,15}(최종|결정)", rep)),
        stop=bool(re.search(r"중단|실패하면|실패 시|미달(이면| 시)|기준에 못|멈춘|접는|재검토", rep)),
    )


def run(cond, i):
    t0 = time.time()
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    r = dict(cond=cond, i=i, report=rep, tokens=tok, sec=round(time.time() - t0, 1), pick=pick(rep), chars=len(rep))
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
            print(c, "선택", dict(sorted(cnt.items())), "| 글자 %d" % (sum(r["chars"] for r in x) / len(x)))
        else:
            s = lambda k: sum(1 for r in x if r[k])
            print(c, "냉동·변질 포함", s("frozen"), "| 지난 데이터", s("real"), "| 담당자 실제 사용 · 시간", s("staff"),
                  "| 자동 환불 포함", s("auto"), "| 중단 규칙", s("stop"), "| 글자 %d" % (sum(r["chars"] for r in x) / len(x)))


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
