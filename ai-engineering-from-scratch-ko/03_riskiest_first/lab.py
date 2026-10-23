# -*- coding: utf-8 -*-
"""ep049 실습 — 시즌 2 3편: 가장 위험한 가정부터 (원본 Phase 14 레슨 49 'Map Assumptions and Resolve the Riskiest One First').
가나다식품(가상) '반품 처리 AI 자동화' 첫 2주 계획을 AI 에게 맡긴다 (2편에서 찾은 업무 흐름이 배경).
배경 사실 중 둘이 숨은 위험이다 — (1) 고객 사진 · 연락처를 외부 AI 로 보내려면 보안팀 사전 승인(규정 한 줄), (2) AI 사진 판정은 아직 아무도 시험 안 함.
조건 (gpt-4.1-mini, 각 10회):
  A 바로 계획     : "첫 2주 계획 짜 줘"
  B 가정부터      : A + "계획 전에, 성공하려면 사실이어야 하는 가정을 먼저 적어"
  C 원작 방식     : B + 5종 분류 · 영향 · 불확실 · 되돌림 점수 · 가장 위험한 열린 가정부터 · 가장 싼 결정적 실험 · 결과 보기 전 기준 · 통과/실패 다음 결정
채점(코드): 보안 확인 · 보안 확인이 개발보다 먼저 · 과거 사진으로 판정 시험 · 미리 정한 기준(숫자) · 실패하면 무엇을 할지 · 2주 안에 사람 확인 없는 자동 환불."""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

CONTEXT = """[배경 — 가나다식품 고객센터 반품 처리]
지금 업무 흐름(지난주 처리 기록으로 확인함):
- 반품 접수(게시판 · 전화) 하루 약 30건, 담당자 2명
- 사진이 있는 건은 품질팀 단톡에 올려 판정을 받는다. 회신까지 1~3시간 — 가장 오래 걸리는 단계
- 3만 원 넘는 환불은 팀장 구두 승인
- 냉동 회수는 택배사 사이트에 다시 입력 (택배사에 회수 접수 API 가 있음 — IT팀 확인 완료)

회사 사정:
- 고객센터 시스템은 사내 서버에 있고, IT팀이 API 를 열어 줄 수 있다
- 반품 사진에는 고객 얼굴 · 주소 라벨 · 연락처가 찍혀 있는 경우가 많다
- 정보보안 규정 7조: 고객 개인정보를 외부 서비스로 보낼 때는 보안팀 사전 승인을 받는다
- 사진을 보고 파손 · 변질을 판정하는 일을 AI 에게 맡겨 본 적은 아직 없다
- 지난 6개월 반품 사진 약 2,400건과 품질팀 판정 결과가 남아 있다
- 경영진은 연말까지 반품 처리 시간을 절반으로 줄이길 원한다

팀은 품질팀 사진 판정을 외부 AI(이미지 판정 API)로 대신하고, 판정이 '파손 맞음'이면 자동 환불까지 이어지게 하는 안을 생각하고 있다."""

ASK = "\n\n이 반품 처리 AI 자동화 프로젝트의 첫 2주 계획을 짜 줘."
ASSUME = "\n\n계획 전에, 이 프로젝트가 성공하려면 사실이어야 하는 가정을 먼저 적어 줘."
METHOD = """

원작 방식으로 해 줘.
1. 가정을 다섯 종류로 나눠 적는다: 가치(그만큼 중요한가) · 사용성(담당자가 쓰고 믿을까) · 실현(가진 데이터와 조건으로 되나) · 지속(비용 · 담당 · 운영) · 안전(틀려도 감당할 수 있나). 반증할 수 있는 문장으로.
2. 가정마다 영향(틀리면 피해) · 불확실(지금 근거가 약함) · 되돌림 어려움을 1~5로 매기고, 점수 = 영향 × 불확실 + 되돌림 어려움.
3. 이미 확인된 가정과 열린 가정을 나누고, 점수가 가장 높은 열린 가정부터 시험한다. 되돌릴 수 없는 일은 증거를 먼저.
4. 실험마다: 틀릴 수 있는 주장 · 현실적인 표본 · 관찰할 결과 · 결과 보기 전에 정한 기준 · 통과 / 실패 / 애매할 때 다음 결정.
5. 아이디어를 만들 수 있다는 걸 보여 주기만 하는 시연은 실험이 아니다."""

COND = {"A": CONTEXT + ASK, "B": CONTEXT + ASSUME + ASK, "C": CONTEXT + ASSUME + METHOD + ASK}

SEC = re.compile(r"보안팀|정보보안|개인정보|보안 규정|7조")
SEC_OK = re.compile(r"승인|검토|협의|확인|심사|문의")
BUILD = re.compile(r"개발|구축|연동|구현|배포|개발 착수|시스템 연결")


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API 실패")


def plan_part(report):
    """'계획' 부분 — 가정 목록 뒤 '2주 계획 · 1주차 · 일정' 제목부터. 없으면 전체."""
    m = re.search(r"^.*(1\s*주\s*차|Week\s*1|\bD-?1\b|1\s*일\s*차|Day\s*1|첫째\s*주|1주\s*\(|^\|?\s*1주).*$", report, re.M)
    return report[m.start():] if m else report


def lines(t):
    return [l for l in t.splitlines() if l.strip()]


def sec_check(report):
    return any(SEC.search(l) and SEC_OK.search(l) for l in lines(report))


def sec_before_build(report):
    """계획 부분에서 보안 확인 줄이 개발 · 연동 줄보다 먼저 나오나 (보안 줄에 개발 말이 같이 있으면 보안 먼저로 본다)."""
    p = lines(plan_part(report))
    si = next((i for i, l in enumerate(p) if SEC.search(l) and SEC_OK.search(l)), None)
    bi = next((i for i, l in enumerate(p) if BUILD.search(l) and not SEC.search(l) and not re.search(r"검증|시험|테스트|평가|계획 수립|요구사항|범위", l)), None)
    if si is None:
        return False
    return bi is None or si <= bi


def past_photo_test(report):
    return any(re.search(r"과거|지난|기존|6개월|2,?400", l) and re.search(r"사진|이미지", l) and re.search(r"정확|일치|비교|판정|시험|테스트|검증", l)
               for l in lines(report))


def threshold(report):
    """판정 정확도 · 일치율 기준을 숫자로 미리 정함 (예: '일치율 90% 이상', '50건 중 45건')."""
    for l in lines(report):
        if re.search(r"정확|일치|오판|판정", l) and re.search(r"\d+\s*%|\d+\s*건\s*중\s*\d+|\d+\s*/\s*\d+", l) and not re.search(r"절반|50\s*%\s*(단축|감소|줄)", l):
            return True
    return False


def fail_decision(report):
    return any(re.search(r"미달|실패|못 미치|낮으면|기준 이하|불합격|통과하지 못|거절되면|승인되지|안 되면|반려", l)
               and re.search(r"중단|보류|재검토|사람|수동|축소|사내|대안|재설계|다시|품질팀|멈|변경|개선|제한|전환|확대", l) for l in lines(report))


def auto_refund_2w(report):
    """2주 계획 안에서 자동 환불을 실제로 돌림(시범 적용 · 운영 · 가동) — 설계 · 검토 · 가정 문장은 제외."""
    for l in lines(plan_part(report)):
        if re.search(r"자동\s*환불|환불\s*자동", l) and re.search(r"시범 적용|적용 시작|운영|가동|오픈|실제 적용|라이브", l)                 and not re.search(r"설계|검토|가능성|위험|피해|동의|이후|3주|않|금지|보류|제외|시 |경우", l):
            return True
    return False


def grade(report):
    g = dict(sec=sec_check(report), sec_first=sec_before_build(report), past=past_photo_test(report),
             thr=threshold(report), fail=fail_decision(report), auto=auto_refund_2w(report), chars=len(report))
    g["all"] = g["sec"] and g["sec_first"] and g["past"] and g["thr"] and g["fail"] and not g["auto"]
    return g


def run(cond, i):
    t0 = time.time()
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    return dict(cond=cond, i=i, report=rep, tokens=tok, sec_s=round(time.time() - t0, 1), **grade(rep))


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        s = lambda k: sum(1 for r in x if r[k])
        print(c, "보안 확인", s("sec"), "| 보안이 개발보다 먼저", s("sec_first"), "| 과거 사진 시험", s("past"), "| 미리 정한 기준", s("thr"),
              "| 실패 시 결정", s("fail"), "| 2주 안 자동환불", s("auto"), "| 모두", s("all"), "/", len(x),
              "| 글자 %d" % (sum(r["chars"] for r in x) / len(x)), "| 토큰 %d" % (sum(r["tokens"] for r in x) / len(x)))


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
