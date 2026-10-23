# -*- coding: utf-8 -*-
"""ep045 실습 — 보너스 1: 기억하는 에이전트, 사용자 메모리 (원서 3장 '사용자 메모리 · 3단계 평가 · 메모리 저장 형식' · 실험 3-1 · 3-2 방식).
가나다식품(가상) 영업지원 에이전트와 거래처 가나마트(가상)의 2026년 6~10월 상담 12회 기록. 질문 12개(3단계 × 4) × 조건 4 × 3회, gpt-4.1-mini.
  M0 기억 없음      : 오늘 질문만
  M1 기록 전부      : 상담 12회 원문을 전부 붙임
  M2 기록에서 찾기  : 상담 1회 = 조각 1개, 질문과 비슷한 상담 3개만 붙임(임베딩 검색)
  M3 메모 카드      : 상담이 끝날 때마다 모델이 JSON 메모 카드를 고쳐 씀(바뀐 사실은 덮어쓰고 이력 남김) → 카드만 붙임. 카드는 회차마다 새로 만듦
채점: 미리 정한 정답 문자열 · 3단계는 '먼저 챙겨야 할 것'을 말했는지. 채점기는 test_grade 로 먼저 시험(ep044 교훈).
병렬 실행 주의: 임베딩 캐시는 스레드 시작 전에 만든다."""
import json, math, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
EMB = "text-embedding-3-small"
TRIALS = 3

S = [  # (날짜, 상담 원문) — 거래처 가나마트 구매팀
 ("2026-06-03", """고객(이수진 과장): 안녕하세요, 가나마트 구매팀 이수진 과장입니다. 이번에 처음 거래 시작하게 됐어요.
상담원: 반갑습니다. 거래처 코드는 GM-2207 로 등록됐습니다.
고객: 세금계산서는 tax@gana-mart.example 로 보내 주세요.
상담원: 네, 등록했습니다. 그 밖에 필요하신 게 있으실까요?
고객: 오늘은 카탈로그만 받아 갈게요. 날씨가 덥네요.
상담원: 네, 여름 행사 품목 위주로 보내 드리겠습니다."""),
 ("2026-06-17", """고객(이수진 과장): 저희 물류센터가 두 곳이에요. 서울 본점 센터는 상온 창고만 있고, 냉동 · 냉장은 이천 2센터에서만 받아요.
상담원: 냉동 · 냉장 제품은 이천 2센터, 상온은 서울 본점 센터로 나눠 보내면 되겠네요.
고객: 네, 섞이면 반품 처리돼요. 참고로 이천은 지게차가 있어서 팔레트로 보내도 됩니다.
상담원: 알겠습니다."""),
 ("2026-07-01", """고객(이수진 과장): 저희 매장 정책이 바뀌었어요. 견과류가 들어간 상품은 포장에 알레르기 표시 스티커를 꼭 붙여서 보내 주셔야 입고가 됩니다.
상담원: 견과 · 땅콩 들어간 제품은 알레르기 스티커 부착, 기억해 두겠습니다.
고객: 그리고 7월 행사 때 냉동만두 반응이 좋았어요. 다음에도 행사 같이 해요."""),
 ("2026-07-15", """고객(이수진 과장): 이천 2센터 냉동 차량 입고는 화요일 · 목요일만 받습니다.
상담원: 냉동 배송은 화 · 목으로 맞추겠습니다.
고객: 결제는 월말 마감하고 익월 15일에 현금으로 드릴게요.
상담원: 네, 결제 조건 등록했습니다."""),
 ("2026-07-29", """고객(이수진 과장): 고추장 500g 단가 문의드려요.
상담원: 박스당 102,000원입니다. 100박스 이상이면 3% 할인됩니다.
고객: 이번엔 40박스만 할게요. 상온이니까 서울 본점으로요.
상담원: 네, 서울 본점 센터로 접수했습니다."""),
 ("2026-08-05", """고객(이수진 과장): 거래처 서류 갱신 건인데요, 저희가 받아 둔 가나다식품 위생 인증서(HACCP 인증서) 사본 유효기간이 2026년 10월 31일까지네요.
상담원: 만료 전에 새 인증서 사본을 보내 드려야겠네요.
고객: 네, 만료되면 그 뒤로는 입고가 막혀요. 꼭 미리 주세요."""),
 ("2026-08-19", """고객(이수진 과장): 8월부터 이천 2센터 냉동 입고 요일이 월 · 수 · 금으로 바뀌었어요.
상담원: 냉동 배송 요일을 월 · 수 · 금으로 바꾸겠습니다.
고객: 네. 그리고 추석 선물세트 견적도 부탁해요."""),
 ("2026-09-02", """고객(이수진 과장): 추석 선물세트는 명절 선물세트 B 로 200세트 할게요. 상온이라 서울 본점으로요.
상담원: 접수했습니다. 9월 20일까지 납품하겠습니다.
고객: 좋아요. 아, 견과 선물세트도 30세트 추가해 주세요.
상담원: 견과 선물세트도 서울 본점으로 같이 보내겠습니다."""),
 ("2026-09-16", """고객(이수진 과장): 죄송해요, 이천 2센터 입고 요일이 다시 화 · 목으로 돌아갔어요. 월 · 수 · 금은 인력이 안 돼서요.
상담원: 냉동 배송 요일을 다시 화 · 목으로 돌리겠습니다.
고객: 네, 앞으로는 계속 화 · 목이에요."""),
 ("2026-09-30", """고객(이수진 과장): 저 다음 달부터 다른 부서로 가요. 10월부터는 박민호 대리가 가나마트 구매 담당입니다.
상담원: 그동안 감사했습니다. 박민호 대리님 연락처를 알 수 있을까요?
고객: 내선 4417 이에요. 메일은 minho.park@gana-mart.example 입니다."""),
 ("2026-10-07", """고객(박민호 대리): 안녕하세요, 새로 맡은 박민호입니다. 결제 조건이 10월분부터 바뀌어요. 월말 마감, 익월 10일 현금입니다.
상담원: 익월 15일에서 10일로 바뀌는 거죠? 10월분부터 반영하겠습니다.
고객: 네. 그 밖에 이수진 과장님이 하던 건 그대로 이어 가면 됩니다."""),
 ("2026-10-14", """고객(박민호 대리): 11월 행사 준비 중인데요, 떡볶이 밀키트도 들여 볼까 해요. 냉동이죠?
상담원: 네, 냉동입니다. 다음 주에 샘플 보내 드릴까요?
고객: 네, 샘플은 사무실(서울 본점)로 한 박스만요. 본 물량은 나중에 정할게요."""),
]

Q = [  # (id, 단계, 질문, 정답 검사, 설명)
 ("L1-1", 1, "가나마트 거래처 코드가 뭐였죠?", lambda t: "GM-2207" in t),
 ("L1-2", 1, "가나마트 세금계산서는 어느 메일로 보내나요?", lambda t: "tax@gana-mart.example" in t),
 ("L1-3", 1, "가나마트 고추장 단가 얼마로 안내했었죠?", lambda t: bool(re.search(r"102,000|10만\s*2천|102000", t))),
 ("L1-4", 1, "가나마트 추석 선물세트는 몇 세트 주문했었죠? (견과 세트 말고)", lambda t: bool(re.search(r"200\s*세트", t))),
 ("L2-1", 2, "가나마트에 냉동만두 50박스 보내려는데 어느 센터로 보내야 하죠?", lambda t: "이천" in t and not re.search(r"서울 본점(으로|에) 보내", t)),
 ("L2-2", 2, "가나마트 이천 2센터 냉동 입고 요일이 지금 언제예요?", lambda t: bool(re.search(r"화(요일)?\s*[·,/와과및 ]+\s*목", t)) and not re.search(r"월\s*[·,/ ]+\s*수\s*[·,/ ]+\s*금(요일)?(로|입니다|이에요)", t)),
 ("L2-3", 2, "가나마트 지금 구매 담당자가 누구고 연락처는요?", lambda t: "박민호" in t and "4417" in t),
 ("L2-4", 2, "가나마트 11월분 대금은 언제 들어와요?", lambda t: bool(re.search(r"10일", t)) and not re.search(r"15일(에|입니다|이에요)", t)),
 ("L3-1", 3, "가나마트 박민호 대리가 '다음 주 월요일(10/26)에 냉동만두 100박스 이천으로 넣어 주세요'래요. 접수 확인 문자 써 줘.",
  lambda t: bool(re.search(r"화|목", t)) and bool(re.search(r"월요일.{0,30}(안|불가|어렵|받지|않)|입고.{0,15}(화|목)", t))),
 ("L3-2", 3, "가나마트에 견과 선물세트 50세트 추가 납품 준비해 줘. 체크할 거 있으면 같이 알려 줘.", lambda t: "알레르기" in t and "서울" in t),
 ("L3-3", 3, "가나마트 11월 행사 물량 납품 일정 잡는 중이야. 11월 5일 첫 납품 전에 챙길 거 있어?", lambda t: "인증서" in t and bool(re.search(r"10월\s*31일|10/31", t))),
 ("L3-4", 3, "가나마트에서 떡볶이 밀키트 본 물량 200박스 주문 들어왔어. 배송 계획 짜 줘.", lambda t: "이천" in t and bool(re.search(r"화|목", t))),
]

SYS = ("너는 가나다식품(가상 회사) 영업지원 에이전트다. 오늘은 2026-10-21(수)이다. 한국어로 짧게 답한다. "
       "거래처에 대해 아래 [기억]에 있는 것만 근거로 쓰고, 없으면 모른다고 한다. 업무를 처리할 때 거래처 조건상 문제가 될 만한 점이 있으면 먼저 짚는다.")
CARD_SYS = ("너는 거래처 메모 관리자다. 상담 한 번이 끝날 때마다 거래처 메모 카드(JSON)를 고쳐 쓴다. 앞으로 업무에 쓸 사실만 남긴다(인사 · 잡담은 버림). "
            "바뀐 사실은 최신 값으로 덮어쓰고, 'history' 에 '언제 무엇이 무엇으로 바뀜'을 한 줄로 남긴다. 날짜 · 금액 · 코드 · 연락처는 원문 그대로. JSON 만 출력한다.")


def chat(msgs, log):
    for k in range(4):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs); break
        except Exception:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    log["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
    return r.choices[0].message.content or ""


def full_text(sessions):
    return "\n\n".join(f"[상담 {d}]\n{t}" for d, t in sessions)


EMB_CACHE = os.path.join(HERE, "emb_sessions.json")


def session_vecs():
    if os.path.exists(EMB_CACHE):
        return json.load(open(EMB_CACHE))
    v = [d.embedding for d in client.embeddings.create(model=EMB, input=[f"[상담 {d}]\n{t}" for d, t in S]).data]
    json.dump(v, open(EMB_CACHE, "w"))
    return v


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def build_card(log):
    card = "{}"
    for d, t in S:
        card = chat([{"role": "system", "content": CARD_SYS},
                     {"role": "user", "content": f"[지금 메모 카드]\n{card}\n\n[새 상담 {d}]\n{t}\n\n고쳐 쓴 메모 카드(JSON):"}], log)
        card = re.sub(r"^```(json)?|```$", "", card.strip(), flags=re.M).strip()
    return card


def memory_for(cond, q, card, vecs, log):
    if cond == "M0":
        return "(기억 없음)"
    if cond == "M1":
        return full_text(S)
    if cond == "M2":
        qv = client.embeddings.create(model=EMB, input=[q]).data[0].embedding
        top = sorted(range(len(S)), key=lambda i: -cos(qv, vecs[i]))[:3]
        log["retrieved"] = [S[i][0] for i in sorted(top)]
        return full_text([S[i] for i in sorted(top)])
    return "[거래처 메모 카드 — 가나마트]\n" + card


def run_trial(cond, seed, vecs):
    log = dict(tokens=0, card_tokens=0)
    card = ""
    if cond == "M3":
        cl = dict(tokens=0)
        card = build_card(cl)
        log["card_tokens"] = cl["tokens"]
    out = []
    for qid, lv, q, chk in Q:
        ql = dict(tokens=0)
        mem = memory_for(cond, q, card, vecs, ql)
        ans = chat([{"role": "system", "content": SYS + "\n\n[기억]\n" + mem}, {"role": "user", "content": q}], ql)
        out.append(dict(cond=cond, seed=seed, q=qid, level=lv, ok=chk(ans), answer=ans[:700], tokens=ql["tokens"], retrieved=ql.get("retrieved")))
    return dict(cond=cond, seed=seed, card=card, card_tokens=log["card_tokens"], answers=out)


if __name__ == "__main__":
    conds = sys.argv[1].split(",") if len(sys.argv) > 1 else ["M0", "M1", "M2", "M3"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    vecs = session_vecs()              # 스레드 시작 전에 한 번만
    jobs = [(c, s) for c in conds for s in range(trials)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: run_trial(j[0], j[1], vecs), jobs))
    json.dump(res, open(os.path.join(HERE, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for c in conds:
        A = [a for r in res if r["cond"] == c for a in r["answers"]]
        print(c, "정답", sum(a["ok"] for a in A), "/", len(A), "|", " ".join(f"L{l} {sum(a['ok'] for a in A if a['level'] == l)}/{sum(1 for a in A if a['level'] == l)}" for l in (1, 2, 3)),
              "| 질문당 토큰", round(sum(a["tokens"] for a in A) / len(A)), "| 카드 만들기 토큰", round(sum(r["card_tokens"] for r in res if r["cond"] == c) / trials))
