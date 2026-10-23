# -*- coding: utf-8 -*-
"""ep048 실습 — 시즌 2 2편: 실제 업무 흐름 찾기 (원본 Phase 14 레슨 48 'Discover the Workflow People Actually Perform').
가나다식품(가상) 고객센터 반품 처리. 공식 매뉴얼은 4단계지만, 실제 기록에는 숨은 일 7가지가 있다(정답표 HIDDEN).
AI 에게 "반품 처리 AI 자동화 설계(현재 업무 흐름 + 자동화할 단계)"를 맡긴다. gpt-4.1-mini, 조건마다 10회.
  A 매뉴얼만
  B 매뉴얼 + 팀장 인터뷰 (전해 들은 말: "매뉴얼대로 해요, 건당 5분" · 사진은 시스템에서 봄 — 실제와 다름)
  C 매뉴얼 + 인터뷰 + 실제 기록 (처리 로그 12건 · 메신저 발췌 · 담당자 메모)
  D C + 원작 방식: 단계마다 행위자 · 근거 · 근거 강도, 마찰 · 숨은 정보 · 권한 · 예외 찾기, 다른 방식은 합치지 말 것
채점(코드): 숨은 일 7가지 중 찾은 수 · 인터뷰의 '건당 5분'을 사실로 씀 · 3만 원 초과 환불을 사람 승인 없이 자동화 · 근거 표시.
test_grade.py 로 채점기 먼저 시험."""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

MANUAL = """[반품 처리 매뉴얼 v3 — 고객센터]
1. 고객센터 시스템에서 반품 접수를 확인한다.
2. 반품 규정(수령 7일 이내, 냉동은 미개봉)에 따라 승인 또는 거절한다.
3. 승인하면 시스템에서 환불을 처리한다.
4. 시스템의 '회수 요청' 버튼으로 택배 회수를 요청한다."""

INTERVIEW = """[고객센터 팀장 인터뷰]
- 매뉴얼대로 해요. 접수 보고, 규정 맞으면 환불하고, 회수 요청 누르면 끝이에요.
- 사진은 고객이 시스템에 첨부하면 담당자가 거기서 보고 판단해요.
- 하루 30건 정도고, 건당 5분이면 돼요."""

RECORDS = """[처리 로그 발췌 — 10월 둘째 주, 담당 정 대리 · 한 주임]
R-1021 월 09:12 접수(게시판) · 냉동만두 포장 파손 · 사진 → 품질팀 단톡에 공유 09:15 · 품질팀 회신 10:40 "파손 맞음" · 환불 10:52 · 회수 요청 10:55
R-1022 월 09:30 접수(게시판) · 고추장 단순 변심 · 수령 3일 · 환불 09:41 · 회수 요청 09:43
R-1024 월 11:05 접수(게시판) · 한우 사골곰탕 세트 42,000원 · 사진 → 품질팀 단톡 · 회신 13:20 · 팀장님께 말로 확인(구두 OK) 13:35 · 환불 13:40
R-1027 화 10:02 전화 접수 · 주문번호 모름 → 고객 전화번호로 주문 조회 10:10 · 두부 상함 · 사진 문자로 받음 → 품질팀 단톡 · 회신 11:30 · 환불 11:36
R-1030 화 14:20 접수(게시판) · 냉동 떡갈비 녹아서 옴 · 품질팀 단톡 회신 15:05 · 환불 15:10 · 회수 요청 버튼 오류(냉동 회수는 시스템 미지원) → 택배사 사이트에 주소 · 품목 · 연락처 다시 입력 15:25
R-1031 화 15:40 접수(게시판) · 간장 단순 변심 · 수령 9일 → 거절 15:44
R-1033 수 09:50 접수(게시판) · 김말이 · 고객 반품 이력 확인(정 대리 개인 엑셀 '주의 고객' 시트) → 이번 달 3번째 → 팀장 보고 후 처리 보류 10:20
R-1035 수 13:10 접수(게시판) · 밀키트 구성품 누락 · 사진 → 품질팀 단톡 · 회신 16:45 · 환불 16:50
R-1036 금 16:40 접수(게시판) · 컵라면 파손 · 정산 마감(금 16시) 지남 → 월요일 환불 메모
R-1038 금 10:15 접수(게시판) · 냉동 군만두 녹음 · 품질팀 단톡 · 회신 11:00 · 환불 11:04 · 회수: 택배사 사이트에 다시 입력 11:18
R-1039 금 11:30 접수(게시판) · 선물세트 58,000원 · 팀장님 외근 → 전화로 구두 OK 14:10 · 환불 14:12
R-1040 금 13:00 접수(게시판) · 떡볶이 떡 단순 변심 · 수령 2일 · 환불 13:09 · 회수 요청 13:10

[팀 메신저 발췌]
정 대리: 저는 사진 먼저 품질팀 단톡에 올리고, 회신 오면 환불하고 회수 걸어요.
한 주임: 저는 회수부터 걸어 둬요. 품질팀 답이 늦어서 고객이 기다리시니까.
정 대리: 그러다 품질팀이 '정상'이라고 하면 회수 취소해야 하잖아요 ㅠ

[정 대리 메모 (개인 노트)]
- 3만 원 넘는 환불은 팀장님께 말로 확인 (시스템엔 승인 칸 없음)
- 냉동 회수는 버튼 안 됨 → 택배사 사이트 직접
- 반품 잦은 고객은 내 엑셀 '주의 고객' 시트 확인"""

TASK = "\n\n우리 고객센터 반품 처리를 AI로 자동화하려고 해. 현재 업무 흐름을 정리하고, 어떤 단계를 어떻게 자동화할지 설계안을 써 줘."
METHOD = """

설계 전에 현재 업무 흐름을 이렇게 정리해 줘.
- 단계마다: 누가 · 무엇을 · 근거(어느 기록에서 봤나) · 근거 강도(직접 기록 / 문서 / 전해 들은 말 / 추측)
- 특히 찾을 것: 마찰(기다림 · 다시 입력), 숨은 정보(개인 메모 · 메신저에만 있는 것), 권한(누가 승인하나), 예외(평소와 다르게 처리한 건)
- 사람마다 방식이 다르면 합치지 말고 따로 적는다.
- 전해 들은 말과 기록이 다르면 기록을 따르고, 다르다고 표시한다."""

COND = {"A": MANUAL + TASK, "B": MANUAL + "\n\n" + INTERVIEW + TASK,
        "C": MANUAL + "\n\n" + INTERVIEW + "\n\n" + RECORDS + TASK,
        "D": MANUAL + "\n\n" + INTERVIEW + "\n\n" + RECORDS + TASK + METHOD}

# 숨은 일 7가지 — (이름, [같은 문단에 모두 있어야 하는 말 묶음들]) 묶음 안은 '하나라도'
HIDDEN = [
    ("품질팀 사진 확인(단톡)", [["품질팀", "품질 팀"], ["사진"]]),
    ("3만 원 초과 팀장 구두 승인", [["팀장"], ["3만", "30,000", "삼만"]]),
    ("반복 반품 고객 개인 엑셀", [["주의 고객", "반품 이력", "반복 반품", "반품이 잦", "반품 잦", "블랙"], ["엑셀", "시트", "개인"]]),
    ("냉동 회수 택배사 사이트 재입력", [["택배사"], ["다시 입력", "재입력", "직접 입력", "수기", "이중 입력", "사이트", "홈페이지"]]),
    ("주문번호 없는 전화 접수", [["전화"], ["주문번호", "전화번호"]]),
    ("금요일 정산 마감 → 월요일", [["정산 마감", "마감 시간", "마감 후", "마감 이후", "마감("], ["금요일", "금 16", "월요일", "16시", "다음 영업일", "다음 주"]]),
    ("담당자마다 순서가 다름", [["정 대리", "한 주임", "담당자마다", "담당자별", "사람마다"], ["회수부터", "회수 먼저", "순서", "방식이 다", "방식 차이", "다르게"]]),
]


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + k * 3)
    raise RuntimeError("API 실패")


def chunks(report):
    """문단(빈 줄 · 제목 · 목록 한 덩어리) 대신 '줄 ± 1줄' 창으로 본다 — 표 한 줄, 목록 한 줄 안에서 같이 나와야 찾은 것."""
    L = [l for l in report.splitlines() if l.strip()]
    return [" ".join(L[max(0, i - 1):i + 2]) for i in range(len(L))] or [""]


def found_hidden(report):
    out = []
    win = chunks(report)
    for name, groups in HIDDEN:
        if any(all(any(w in c for w in g) for g in groups) for c in win):
            out.append(name)
    return out


def took_5min(report):
    """인터뷰의 '건당 5분'을 지금 처리 시간으로 그대로 씀 — '5분 → 1~2분' 같은 효과 계산 포함. 기록과 다르다는 표시가 있으면 제외."""
    for line in report.splitlines():
        if re.search(r"(?<!\d)5\s*분", line) and not re.search(r"다르|실제로는|기록상|기록과|불일치|차이|전해 들은|과소|더 오래|대기 시간 제외|넘", line):
            return True
    return False


def auto_approve(report):
    """3만 원 넘는 환불을 사람 승인 없이 AI · 시스템이 승인/처리하게 설계했나."""
    for c in chunks(report):
        if re.search(r"3만|30,000", c) and re.search(r"자동\s*(승인|환불|처리)", c) and not re.search(r"팀장|사람|담당자 확인|승인 요청|결재|수동", c):
            return True
    return False


def evidence_tags(report):
    return len(re.findall(r"직접 기록|전해 들은|추측|근거 강도|로그 R-\d+|R-\d{4}", report))


def grade(report):
    h = found_hidden(report)
    return dict(hidden=h, n_hidden=len(h), took5=took_5min(report), auto=auto_approve(report),
                evid=evidence_tags(report), chars=len(report))


def run(cond, i):
    t0 = time.time()
    rep, tok = chat([{"role": "user", "content": COND[cond]}])
    return dict(cond=cond, i=i, report=rep, tokens=tok, sec=round(time.time() - t0, 1), **grade(rep))


def summary(rs):
    for c in sorted({r["cond"] for r in rs}):
        x = [r for r in rs if r["cond"] == c]
        cnt = {n: sum(1 for r in x if n in r["hidden"]) for n, _ in HIDDEN}
        print(c, "숨은 일 평균 %.1f/7" % (sum(r["n_hidden"] for r in x) / len(x)), "| 5분 그대로", sum(r["took5"] for r in x),
              "| 자동승인", sum(r["auto"] for r in x), "| 근거표시 평균 %.1f" % (sum(r["evid"] for r in x) / len(x)),
              "| 글자 %d" % (sum(r["chars"] for r in x) / len(x)), "| 토큰 %d" % (sum(r["tokens"] for r in x) / len(x)))
        print("   ", cnt)


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
