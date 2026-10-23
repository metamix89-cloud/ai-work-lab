# -*- coding: utf-8 -*-
"""ep044 실습 — 여러 에이전트가 일을 나눌 때 (원서 10장 '멀티 에이전트가 정말 나은 때' 표 10-1 · 실패 모드 '오류의 연쇄 증폭', 가나다식품으로 각색).
품질 클레임 12건(가상) × 조건 4 × 3회, gpt-4.1-mini. 모든 도구는 가짜(돈 · 쿠폰이 실제로 나가지 않음).
  SOLO     : 에이전트 하나가 모든 도구 · 규칙으로 처리
  CHAIN    : 접수 → 품질 → 정산 세 에이전트. 앞 에이전트가 쓴 '인계 메모'만 다음에 넘어감(공유 컨텍스트 없음)
  SELF     : SOLO 처리 뒤, 같은 모델 검토자가 '처리 기록 글'만 읽고 고칠 점이 있으면 다시 처리하게 함 (새 정보 없음)
  VERIFY   : SOLO 처리 뒤, 검토자가 주문 · 로트 · 클레임 이력 도구로 직접 확인하고 다시 처리하게 함 (새 정보 있음)
채점: 최종 실행된 처리(환불 금액 · 쿠폰 · 팀장 승인 · 사진 요청 · 현장 확인 요청)가 정답과 같으면 정답.
병렬 실행 주의(ep041 에서 겪은 실수): 결과 파일은 메인에서 한 번만 쓴다.
겪은 실수(2026-10-21): ① 규칙 5 문구 수정이 셸 치환에서 빠진 채 실행이 시작돼 중단하고 다시 돌림 ② SELF 검토자 응답을 글 대신 메시지 객체로 다뤄 36번 모두 오류 → 고쳐서 SELF 만 다시(results_self.json).
  ③ 가짜 클레임 이력 도구가 없는 고객 번호(주문번호 · '고객 번호' 글자)에도 '0회'라고 답해, 에이전트의 잘못된 조회가 조용히 통과됨
     → 없는 번호면 오류를 돌려주게 고치고 네 조건 모두 다시(results_v2.json). 화면 숫자는 v2."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = 3

ORDERS = {  # 주문: 고객, 상품, 금액, 로트
    "GND-5001": ("C-301", "냉동만두 1kg", 12900, "L2610-03"), "GND-5002": ("C-302", "떡볶이 밀키트", 15900, "L2610-11"),
    "GND-5003": ("C-303", "고추장 500g", 8500, "L2609-21"), "GND-5004": ("C-304", "한우 선물세트", 89000, "L2610-15"),
    "GND-5005": ("C-305", "어묵탕 세트", 15900, "L2610-08"), "GND-5006": ("C-306", "참기름 350ml", 9800, "L2609-30"),
    "GND-5007": ("C-307", "냉동만두 1kg", 12900, "L2610-03"), "GND-5008": ("C-308", "명절 선물세트", 68000, "L2610-02"),
    "GND-5009": ("C-309", "두부 2입", 3800, "L2610-19"), "GND-5010": ("C-310", "떡볶이 밀키트", 15900, "L2610-12"),
    "GND-5011": ("C-311", "수제 떡갈비", 23900, "L2610-17"), "GND-5012": ("C-312", "들기름 김자반", 6900, "L2610-05"),
}
LOTS = {"L2610-03": "리콜", "L2610-11": "이상 없음", "L2609-21": "이상 없음", "L2610-15": "리콜", "L2610-08": "이상 없음", "L2609-30": "이상 없음",
        "L2610-02": "이상 없음", "L2610-19": "리콜", "L2610-12": "이상 없음", "L2610-17": "이상 없음", "L2610-05": "리콜"}
HISTORY = {"C-305": 2, "C-310": 2, "C-311": 1}   # 최근 30일 이전 클레임 수 (나머지 0)
# (주문, 고객 말, 사진 있음, 정답)
CASES = [
    ("GND-5001", "만두에서 플라스틱 조각이 나왔어요.", False, dict(refund=12900, coupon=True)),
    ("GND-5002", "밀키트 소스가 상한 것 같아요. 사진 보냈어요.", True, dict(refund=15900)),
    ("GND-5003", "고추장 맛이 이상해요.", False, dict(photo=True)),
    ("GND-5004", "한우 색이 변했어요.", False, dict(escalate=True)),
    ("GND-5005", "어묵탕에서 이상한 냄새가 나요. 사진 첨부했어요.", True, dict(field=True)),
    ("GND-5006", "참기름 쩐내가 나요. 사진 있어요.", True, dict(refund=9800)),
    ("GND-5007", "만두 포장이 터져서 왔어요. 사진 보냈어요.", True, dict(refund=12900, coupon=True)),
    ("GND-5008", "선물세트 안에 곰팡이가 있어요. 사진 있어요.", True, dict(escalate=True)),
    ("GND-5009", "두부가 시큼해요.", False, dict(refund=3800, coupon=True)),
    ("GND-5010", "밀키트 떡이 딱딱해요. 사진 있어요.", True, dict(field=True)),
    ("GND-5011", "떡갈비 고기 색이 이상해요. 사진 보냈어요.", True, dict(refund=23900)),
    ("GND-5012", "김자반에 이물질이 있어요.", False, dict(refund=6900, coupon=True)),
]
RULES = ("[품질 클레임 규칙]\n1. 주문의 로트 번호로 로트 상태를 확인한다.\n"
         "2. 로트가 '리콜'이면 사진 없이도 전액 환불하고 보상 쿠폰 5,000원을 발급한다.\n"
         "3. 로트가 '이상 없음'이면 고객 사진이 있을 때만 전액 환불한다. 사진이 없으면 사진을 요청한다(환불 보류).\n"
         "4. 고객의 최근 30일 이전 클레임이 2회 이상이면 환불하지 말고 품질팀 현장 확인을 요청한다(리콜 로트는 예외 없이 2번 규칙).\n"
         "5. 결제 금액이 50,000원을 넘으면 환불 · 쿠폰 모두 직접 하지 말고 팀장 승인만 요청한다(로트 상태와 상관없이).\n"
         "6. 한 클레임에 처리는 한 번만 한다.")


def fn(name, d, props):
    return {"type": "function", "function": {"name": name, "description": d, "parameters": {
        "type": "object", "properties": props, "required": list(props)}}}


S = lambda d: {"type": "string", "description": d}
T = {
    "get_order": fn("get_order", "주문(고객 번호 · 상품 · 결제 금액 · 로트 번호)을 조회한다.", {"order_id": S("주문번호")}),
    "get_claim_history": fn("get_claim_history", "고객의 최근 30일 이전 클레임 횟수를 조회한다.", {"customer_id": S("고객 번호")}),
    "get_lot_status": fn("get_lot_status", "로트 번호의 품질 상태('리콜' / '이상 없음')를 조회한다.", {"lot": S("로트 번호")}),
    "refund": fn("refund", "환불을 실행한다. 되돌릴 수 없다.", {"order_id": S("주문번호"), "amount": {"type": "integer"}}),
    "issue_coupon": fn("issue_coupon", "보상 쿠폰을 발급한다.", {"customer_id": S("고객 번호"), "amount": {"type": "integer"}}),
    "escalate": fn("escalate", "팀장 승인을 요청한다.", {"order_id": S("주문번호"), "reason": S("이유")}),
    "request_photo": fn("request_photo", "고객에게 사진을 요청한다.", {"order_id": S("주문번호")}),
    "request_field_check": fn("request_field_check", "품질팀 현장 확인을 요청한다.", {"order_id": S("주문번호"), "reason": S("이유")}),
}
READ = ["get_order", "get_claim_history", "get_lot_status"]
ACT = ["refund", "issue_coupon", "escalate", "request_photo", "request_field_check"]


def tool_out(n, a, st):
    if n == "get_order":
        o = ORDERS.get(a.get("order_id"))
        return {"오류": "없는 주문"} if not o else {"order_id": a["order_id"], "고객": o[0], "상품": o[1], "결제금액": o[2], "로트": o[3]}
    if n == "get_claim_history":
        cid = a.get("customer_id")
        if cid not in {o[0] for o in ORDERS.values()}:   # 첫 실행엔 없는 번호에도 0회라고 답하던 버그 → 고침
            return {"오류": f"없는 고객 번호: {cid}. 고객 번호는 C- 로 시작한다(주문 조회 결과의 '고객')."}
        return {"고객": cid, "최근30일_이전클레임": HISTORY.get(cid, 0)}
    if n == "get_lot_status":
        return {"로트": a.get("lot"), "상태": LOTS.get(a.get("lot"), "알 수 없음")}
    st["acts"].append((n, a))
    return {"ok": True}


def chat(msgs, tools, st):
    for k in range(4):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, tools=tools) if tools else client.chat.completions.create(model=MODEL, messages=msgs)
            break
        except Exception:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    st["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
    st["calls"] += 1
    return r.choices[0].message


def agent(sys_txt, user, names, st, max_turns=10):
    tools = [T[n] for n in names]
    msgs = [{"role": "system", "content": sys_txt}, {"role": "user", "content": user}]
    for _ in range(max_turns):
        m = chat(msgs, tools, st)
        if not m.tool_calls:
            return m.content or ""
        msgs.append(m)
        for tc in m.tool_calls:
            a = json.loads(tc.function.arguments or "{}")
            st["log"].append(f"{tc.function.name}({json.dumps(a, ensure_ascii=False)})")
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_out(tc.function.name, a, st), ensure_ascii=False)})
    return "(턴 한도)"


def claim_text(case):
    oid, msg, photo, _ = case
    return f"[클레임] 주문 {oid}: \"{msg}\" (첨부 사진: {'있음' if photo else '없음'})"


BASE = "너는 가나다식품(가상 회사) 품질 클레임 담당 에이전트다. 도구로 확인한 사실에 따라 처리하고 결과를 짧게 알린다.\n" + RULES


def run(cond, case):
    st = dict(tokens=0, calls=0, acts=[], log=[], notes=[], review="")
    if cond in ("SOLO", "SELF", "VERIFY"):
        out = agent(BASE, claim_text(case), READ + ACT, st)
        if cond in ("SELF", "VERIFY"):
            record = claim_text(case) + "\n[처리 기록]\n" + "\n".join(st["log"]) + "\n[처리 결과 답변]\n" + out
            if cond == "SELF":
                rv = chat([{"role": "system", "content": "너는 품질 클레임 처리 검토자다.\n" + RULES + "\n아래 처리 기록 글만 보고, 규칙에 어긋난 점이 있으면 '수정 필요: 무엇을 어떻게' 로, 없으면 '문제 없음' 으로 답하라."},
                           {"role": "user", "content": record}], None, st).content or ""
            else:
                rv = agent("너는 품질 클레임 처리 검토자다.\n" + RULES + "\n조회 도구로 주문 · 로트 · 클레임 이력을 직접 확인해, 처리 기록이 규칙에 맞는지 검토하라. "
                           "어긋나면 '수정 필요: 무엇을 어떻게' 로, 맞으면 '문제 없음' 으로 답하라. 처리 도구는 없다.", record, READ, st)
            st["review"] = rv[:600]
            if "수정 필요" in rv:
                acts_before = list(st["acts"])
                fix = agent(BASE + "\n이미 실행한 처리는 취소할 수 없다. 검토 의견에 따라 빠진 처리만 추가하고, 이미 한 처리는 다시 하지 않는다.",
                            record + "\n[검토 의견]\n" + rv, READ + ACT, st)
                st["fix"] = fix[:400]
    else:  # CHAIN
        n1 = agent("너는 고객센터 접수 에이전트다. 주문과 고객 클레임 이력을 조회하고, 다음 담당(품질팀 에이전트)에게 넘길 인계 메모를 쓴다. "
                   "다음 담당은 이 메모만 본다. 처리 도구는 없다.\n" + RULES, claim_text(case), ["get_order", "get_claim_history"], st)
        st["notes"].append(n1[:800])
        n2 = agent("너는 품질팀 에이전트다. 받은 인계 메모를 보고 로트 상태를 확인해 처리 방침(환불 여부 · 금액 · 쿠폰 · 사진 요청 · 현장 확인 · 팀장 승인)을 정하고, "
                   "다음 담당(정산 에이전트)에게 넘길 인계 메모를 쓴다. 다음 담당은 이 메모만 본다. 처리 도구는 없다.\n" + RULES, "[접수 인계 메모]\n" + n1, ["get_lot_status"], st)
        st["notes"].append(n2[:800])
        agent("너는 정산 에이전트다. 받은 인계 메모의 처리 방침대로 처리 도구를 실행한다. 조회 도구는 없다.\n" + RULES, "[품질팀 인계 메모]\n" + n2, ACT, st)
    return st


def grade(gold, acts):
    got = dict(refund=None, coupon=False, escalate=False, photo=False, field=False)
    # 0원 환불 · 0원 쿠폰은 돈이 나가지 않으므로 처리로 세지 않는다 (첫 채점기는 이것도 '발급'으로 셌음 → 고침)
    amt = lambda a: int(a.get("amount") or 0)
    acts = [(n, a) for n, a in acts if not (n in ("refund", "issue_coupon") and amt(a) <= 0)]
    refunds = [amt(a) for n, a in acts if n == "refund"]
    if refunds:
        got["refund"] = refunds if len(refunds) > 1 else refunds[0]
    got["coupon"] = any(n == "issue_coupon" for n, a in acts)
    got["escalate"] = any(n == "escalate" for n, a in acts)
    got["photo"] = any(n == "request_photo" for n, a in acts)
    got["field"] = any(n == "request_field_check" for n, a in acts)
    want = dict(refund=gold.get("refund"), coupon=gold.get("coupon", False), escalate=gold.get("escalate", False),
                photo=gold.get("photo", False), field=gold.get("field", False))
    return got == want, got


def one(job):
    cond, case, seed = job
    try:
        st = run(cond, case)
    except Exception as e:
        return dict(cond=cond, case=case[0], seed=seed, error=str(e)[:300])
    ok, got = grade(case[3], st["acts"])
    wrong_money = got["refund"] not in (None, case[3].get("refund")) or (got["refund"] is not None and "refund" not in case[3]) or (got["coupon"] and not case[3].get("coupon"))
    return dict(cond=cond, case=case[0], seed=seed, ok=ok, got=got, gold=case[3], wrong_money=bool(wrong_money), tokens=st["tokens"], calls=st["calls"],
                log=st["log"], notes=st["notes"], review=st["review"], fix=st.get("fix", ""))


if __name__ == "__main__":
    conds = sys.argv[1].split(",") if len(sys.argv) > 1 else ["SOLO", "CHAIN", "SELF", "VERIFY"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    out = sys.argv[3] if len(sys.argv) > 3 else "results.json"
    jobs = [(c, cs, s) for c in conds for cs in CASES for s in range(trials)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, jobs))
    json.dump(res, open(os.path.join(HERE, out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for c in conds:
        rs = [r for r in res if r["cond"] == c and "error" not in r]
        print(c, "정답", sum(r["ok"] for r in rs), "/", len(rs), "· 잘못 나간 돈", sum(r["wrong_money"] for r in rs),
              "· 평균 토큰", round(sum(r["tokens"] for r in rs) / max(1, len(rs))), "· 평균 호출", round(sum(r["calls"] for r in rs) / max(1, len(rs)), 1),
              "· 오류", sum(1 for r in res if r["cond"] == c and "error" in r))
