# -*- coding: utf-8 -*-
"""ep035 실습 — 시스템 프롬프트 · 도구 설명이 성능을 바꾸는가 (원서 2장 실험 2-4 방식, 가나다식품 반품 상담으로 각색).
조건 5개 × 상담 10건 × 3회 실제 실행 → results.json. 채점은 도구 호출 기록으로 자동 (정답은 사람이 미리 정함).
  A 기준        : 단계별 절차(SOP) + 구체적 규칙 + 도구 설명 완전 + 중립 어조
  B 어조만      : A 와 같은 내용, 과장된 말투 · 이모지
  C 뒤섞기      : 같은 규칙을 번호 없이 순서를 섞어 나열
  D 도구설명 없음: 도구 이름 · 인자 이름만, 설명 문장 전부 제거
  E 모호한 규칙 : '상황에 맞게 알맞게' 처럼 규칙을 흐리게"""
import json, random, sys
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"

# ── 가상 데이터 (받은 지 며칠인지 미리 계산해 둠: 날짜 계산 실수는 이번 실험의 관심 밖)
CUSTOMERS = {"GND-3101": "5521", "GND-3102": "1180", "GND-3103": "7304", "GND-3104": "2209", "GND-3105": "6612",
             "GND-3106": "3047", "GND-3107": "8890", "GND-3108": "4415", "GND-3109": "9031", "GND-3110": "1276"}
ORDERS = {
    "GND-3101": dict(상품="가나다 냉동만두 1kg", 분류="냉동식품", 금액=12900, 받은지_일=5, 개봉="아니오"),
    "GND-3102": dict(상품="가나다 냉동만두 1kg", 분류="냉동식품", 금액=12900, 받은지_일=10, 개봉="아니오"),
    "GND-3103": dict(상품="가나다 참기름 350ml", 분류="상온식품", 금액=9800, 받은지_일=9, 개봉="예"),
    "GND-3104": dict(상품="가나다 고추장 500g", 분류="상온식품", 금액=8500, 받은지_일=3, 개봉="예"),
    "GND-3105": dict(상품="가나다 명절 선물세트", 분류="상온식품", 금액=68000, 받은지_일=2, 개봉="아니오"),
    "GND-3106": dict(상품="가나다 냉동만두 1kg", 분류="냉동식품", 금액=12900, 받은지_일=4, 개봉="예"),
    "GND-3107": dict(상품="가나다 어묵탕 세트", 분류="냉동식품", 금액=15900, 받은지_일=3, 개봉="아니오"),
    "GND-3108": dict(상품="가나다 떡볶이 밀키트", 분류="냉동식품", 금액=15900, 받은지_일=2, 개봉="아니오"),
    "GND-3109": dict(상품="가나다 떡볶이 밀키트", 분류="냉동식품", 금액=6900, 받은지_일=7, 개봉="아니오"),
    "GND-3110": dict(상품="가나다 한우 선물세트", 분류="냉동식품", 금액=89000, 받은지_일=1, 개봉="예"),
}
# (고객 메시지, 정답 처리) — refund:금액 / escalate / deny / ask
CASES = [
    ("주문 GND-3101 반품하고 싶어요. 그냥 마음이 바뀌었어요. 전화번호 뒷자리 5521입니다.", ("refund", 9900)),
    ("GND-3102 냉동만두 반품해 주세요. 안 뜯었어요. 뒷자리 1180.", ("deny", None)),
    ("참기름(GND-3103) 써 봤는데 입에 안 맞아서 환불 원해요. 뒷자리 7304.", ("deny", None)),
    ("GND-3104 고추장에서 시큼한 냄새가 나요. 변질된 것 같아요. 환불해 주세요. 뒷자리 2209입니다.", ("refund", 8500)),
    ("선물세트 GND-3105 받는 분이 필요 없다고 해서 반품합니다. 뒷자리 6612.", ("escalate", None)),
    ("GND-3106 만두에서 플라스틱 조각이 나왔어요. 환불해 주세요. 뒷자리 3047.", ("refund", 12900)),
    ("GND-3107 반품할게요. 단순 변심입니다. 뒷자리 1234.", ("deny_verify", None)),
    ("GND-3108 떡볶이 반품하고 싶어요. 아직 안 뜯었어요.", ("ask", None)),
    ("GND-3109 떡볶이 반품해 주세요. 마음이 바뀌었어요. 오늘 받은 지 딱 일주일이에요. 뒷자리 9031.", ("refund", 3900)),
    ("GND-3110 한우 세트 고기 색이 이상하고 냄새가 나요. 환불해 주세요. 뒷자리 1276.", ("escalate", None)),
]

# ── 도구
TOOL_DESC = {
    "verify_customer": ("주문번호와 고객이 말한 휴대폰 번호 뒤 4자리가 일치하는지 확인한다. 환불 · 승인 요청 전에 반드시 먼저 호출한다.",
                        {"order_id": "주문번호. 예: GND-3101", "phone_last4": "고객이 말한 휴대폰 번호 뒤 4자리 숫자"}),
    "get_order": ("주문 상품 · 분류(냉동식품/상온식품) · 결제 금액(원) · 받은 지 며칠 · 개봉 여부를 조회한다.",
                  {"order_id": "주문번호. 예: GND-3101"}),
    "refund": ("고객에게 환불을 실행한다. 되돌릴 수 없다. 금액은 규칙에 따라 계산한 최종 환불액(원, 정수).",
               {"order_id": "주문번호", "amount": "환불할 금액(원). 정수", "reason": "'단순 변심' 또는 '품질 문제'"}),
    "escalate": ("직접 처리하지 않고 사람 상담원의 승인을 요청한다.",
                 {"order_id": "주문번호", "reason": "승인이 필요한 이유 한 줄"}),
}


def tools(with_desc=True):
    out = []
    for name, (desc, params) in TOOL_DESC.items():
        props = {k: ({"type": "integer"} if k == "amount" else {"type": "string"}) for k in params}
        if with_desc:
            for k in props:
                props[k]["description"] = params[k]
        f = {"name": name, "parameters": {"type": "object", "properties": props, "required": list(params)}}
        if with_desc:
            f["description"] = desc
        out.append({"type": "function", "function": f})
    return out


# ── 시스템 프롬프트 (조건별)
RULES = [
    "본인 확인: 환불이나 승인 요청 전에 verify_customer 로 주문번호와 휴대폰 뒤 4자리를 확인한다. 고객이 뒤 4자리를 말하지 않았으면 처리하지 말고 먼저 물어본다. 일치하지 않으면 처리하지 않는다.",
    "반품 기간: 냉동식품은 받은 지 7일 이내(7일째 포함), 상온식품은 14일 이내만 반품할 수 있다.",
    "개봉 상품: 개봉한 상품은 단순 변심으로 반품할 수 없다. 단, 품질 문제(이물 · 변질 · 이상한 냄새 등)는 개봉했어도 반품할 수 있다.",
    "환불 금액: 단순 변심은 결제 금액에서 반품 배송비 3,000원을 뺀다. 품질 문제는 결제 금액 전액을 환불한다.",
    "고액 승인: 결제 금액이 50,000원을 넘으면 사유와 관계없이 refund 하지 말고 escalate 로 상담원 승인을 요청한다.",
]
SOP = """# 역할
가나다식품 고객센터 반품 · 환불 담당 상담원. 오늘 고객 메시지 하나를 처리한다.

# 처리 절차
1단계 본인 확인 — {0}
2단계 주문 조회 — get_order 로 분류 · 금액 · 받은 지 며칠 · 개봉 여부를 확인한다.
3단계 고액 확인 — {4}
4단계 반품 가능 판단 — {1} {2}
5단계 금액 계산과 실행 — {3} 계산한 금액으로 refund 를 호출한다.
6단계 안내 — 처리 결과(또는 반품이 안 되는 이유)를 고객에게 두 문장 안으로 안내한다."""
TONE_B = """🎉🎉 안녕하세요~~ 저는 우주 최고의 가나다식품 반품 요정이에요!! ✨ 고객님 기분이 최고가 되도록 완전 열심히 할게요 💖💖
(진짜 진짜 중요한 거 알려 드릴게요 👇👇)
"""


def system_prompt(cond, seed=0):
    body = [r.split(": ", 1)[1] for r in RULES]
    if cond in ("A", "D"):
        return SOP.format(*body)
    if cond == "B":
        return TONE_B + SOP.format(*body).replace("두 문장 안으로 안내한다.", "신나고 귀엽게 이모지 듬뿍 넣어 안내한다 🥳")
    if cond == "C":
        bits = body + ["get_order 로 주문을 조회한다.", "처리 결과를 고객에게 두 문장 안으로 안내한다."]
        sents = [s.strip() + ("" if s.strip().endswith(".") else ".") for b in bits for s in b.split(". ") if s.strip()]
        random.Random(seed).shuffle(sents)
        return "가나다식품 고객센터 반품 · 환불 담당 상담원이다. 다음을 지킨다. " + " ".join(sents)
    if cond == "E":
        return ("가나다식품 고객센터 반품 · 환불 담당 상담원이다. 고객이 만족하도록 상황에 맞게 반품 · 환불을 처리한다. "
                "필요하면 본인 확인을 하고, 반품 기간과 상품 상태를 적절히 고려한다. 금액은 합리적으로 정하고, 큰 금액은 신중하게 다룬다. "
                "처리 결과를 고객에게 두 문장 안으로 안내한다.")


# ── 도구 실행 + 핵심 루프
def run_tool(name, a):
    oid = a.get("order_id")
    if name == "verify_customer":
        if oid not in CUSTOMERS:
            return {"오류": "없는 주문번호"}
        return {"일치": CUSTOMERS[oid] == str(a.get("phone_last4", "")).strip()}
    if name == "get_order":
        return ORDERS.get(oid, {"오류": "없는 주문번호"})
    if name == "refund":
        if oid not in ORDERS or not isinstance(a.get("amount"), int):
            return {"오류": "주문번호 또는 금액 형식이 잘못됨"}
        return {"환불 완료": a["amount"]}
    if name == "escalate":
        return {"접수": "상담원 승인 대기"}
    return {"오류": "없는 도구"}


def agent(cond, msg, seed):
    messages = [{"role": "system", "content": system_prompt(cond, seed)}, {"role": "user", "content": msg}]
    log, final = [], ""
    for _ in range(10):
        m = client.chat.completions.create(model=MODEL, messages=messages, tools=tools(cond != "D")).choices[0].message
        messages.append(m)
        if not m.tool_calls:
            final = m.content or ""
            break
        for tc in m.tool_calls:
            try:
                a = json.loads(tc.function.arguments)
            except Exception:
                a = {}
            r = run_tool(tc.function.name, a)
            log.append({"tool": tc.function.name, "args": a, "result": r})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(r, ensure_ascii=False)})
    return log, final


def grade(gold, log):
    kind, amt = gold
    names = [l["tool"] for l in log]
    refunds = [l for l in log if l["tool"] == "refund"]
    escal = "escalate" in names
    verified_ok = any(l["tool"] == "verify_customer" and l["result"].get("일치") is True for l in log)
    first_act = next((i for i, n in enumerate(names) if n in ("refund", "escalate")), None)
    first_ok_verify = next((i for i, l in enumerate(log) if l["tool"] == "verify_customer" and l["result"].get("일치") is True), None)
    v = {"순서 위반": first_act is not None and (first_ok_verify is None or first_ok_verify > first_act),
         "도구 오류": sum(1 for l in log if "오류" in l["result"])}
    if kind == "refund":
        ok = len(refunds) == 1 and refunds[0]["args"].get("amount") == amt and not escal
        why = "정답" if ok else ("금액 틀림 %s" % refunds[0]["args"].get("amount") if refunds else ("승인 요청함" if escal else "환불 안 함"))
    elif kind == "escalate":
        ok = escal and not refunds
        why = "정답" if ok else ("고액을 바로 환불" if refunds else "승인 요청 안 함")
    else:   # deny · deny_verify · ask : 아무것도 실행하지 않아야 함
        ok = not refunds and not escal
        why = "정답" if ok else ("규칙 어기고 환불" if refunds else "불필요한 승인 요청")
    if kind == "ask" and ok and verified_ok:
        ok, why = False, "번호 없이 확인 통과?"
    v.update(ok=ok and not v["순서 위반"], why=why if not (ok and v["순서 위반"]) else "확인 전에 실행")
    return v


def one(job):
    cond, ci, rep = job
    msg, gold = CASES[ci]
    log, final = agent(cond, msg, seed=rep)
    return dict(cond=cond, case=ci, rep=rep, msg=msg, gold=gold, log=log, final=final, **grade(gold, log))


if __name__ == "__main__":
    REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    jobs = [(c, i, r) for c in "ABCDE" for i in range(len(CASES)) for r in range(REPS)]
    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(one, jobs))
    json.dump(res, open("results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for c in "ABCDE":
        rs = [r for r in res if r["cond"] == c]
        print(c, "정답 %d/%d" % (sum(r["ok"] for r in rs), len(rs)), "· 순서 위반 %d" % sum(r["순서 위반"] for r in rs),
              "· 도구 오류 %d" % sum(r["도구 오류"] for r in rs))
