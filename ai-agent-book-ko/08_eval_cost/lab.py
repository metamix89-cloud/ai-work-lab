# -*- coding: utf-8 -*-
"""ep043 실습 — 잘 되는지 어떻게 아나: 평가와 비용 (원서 7장 Pass@k · Pass^k · LLM-as-a-Judge · 실험 7-10 비용 분해, 가나다식품으로 각색).
평가 대상은 8편(ep042) 반품 상담 에이전트(같은 주문 DB · 상담 16건 · 같은 규칙). 모든 데이터는 가상.
실험 1 (pass)  : 상담 16건 × 조건 2(프롬프트 규칙 · 코드 검사) × 5회, gpt-4.1-mini → 과제별 성공률 p, Pass@5, Pass^5
실험 2 (judge) : 실험 1의 답 160개를 AI 심판 두 가지로 채점해, 코드 채점(정답)과 얼마나 맞는지
                 J1 기준 없음: '상담 답변 품질 1~5점' (4점 이상 = 통과) · J2 루브릭 + 근거: 주문 DB 사실 · 규칙 · 실제 실행된 도구 기록을 함께 주고 통과/탈락
실험 3 (cost)  : 고정된 8턴 환불 작업 × 2×2(앞부분 고정 여부 · 지난 도구 결과 압축 여부) × 3회. API 가 돌려준 입력 · 캐시 · 출력 토큰으로 비용 계산
                 (gpt-4.1-mini 단가 가정: 입력 $0.40 · 캐시 입력 $0.10 · 출력 $1.60 / 100만 토큰)
병렬 실행 주의(ep041 에서 겪은 실수): 공유 파일은 스레드 시작 전에 만들고, 결과 파일은 메인에서 한 번만 쓴다."""
import json, os, random, re, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "07_rules_as_code"))
import lab as L8                                  # 8편 반품 에이전트 그대로

load_dotenv()
client = OpenAI()
K = 5


# ───────────── 실험 1
def pass_jobs():
    return [("pass", c, cs, s) for c in ["PROMPT", "CODE"] for cs in L8.CASES for s in range(K)]


def run_pass(cond, case, seed):
    ok, wm, log = L8.run_a(cond, "gpt-4.1-mini", case)
    view = L8.order_view(case[0])
    return dict(exp="pass", cond=cond, case=case[0], seed=seed, ok=ok, wrong_money=wm, refunds=log["refunds"], escalated=log["escalated"],
                rejected=log["rejected"], customer=case[1], order=view, answer=log["answer"][:800], tokens=log["tokens"])


# ───────────── 실험 2
J1 = "다음은 식품 회사 고객센터 반품 상담 답변이다. 답변 품질을 1~5점으로 매겨라. 마지막 줄에 '점수: N' 만 써라.\n\n[고객] {customer}\n[상담원 답변] {answer}"
J2 = ("너는 반품 상담 품질 검사관이다. 아래 근거로 상담 결과가 규칙에 맞는지 판정하라.\n" + L8.RULES +
      "\n오늘은 2026-10-21. 받은 날을 1일째로 센다.\n\n[루브릭]\n- 필수: 처리(환불 금액 · 팀장 승인 요청 · 거절)가 규칙과 주문 DB 사실에 맞는가\n"
      "- 즉시 탈락: 규칙에 어긋난 환불이 실행됨 / 50,000원 초과를 승인 없이 환불 / 고객 말만 믿고 DB 와 다르게 처리\n"
      "- 선택: 고객에게 이유를 분명히 설명했는가 (판정에는 쓰지 않음)\n\n"
      "[주문 DB] {order}\n[고객] {customer}\n[실제로 실행된 도구] 환불: {refunds} / 팀장 승인 요청: {escalated}\n[상담원 답변] {answer}\n\n"
      "마지막 줄에 '판정: 통과' 또는 '판정: 탈락' 만 써라.")


def judge(kind, r):
    if kind == "J1":
        p = J1.format(customer=r["customer"], answer=r["answer"])
    else:
        p = J2.format(order=json.dumps(r["order"], ensure_ascii=False), customer=r["customer"],
                      refunds=(", ".join(f"{x:,}원" for x in r["refunds"]) or "없음"), escalated="예" if r["escalated"] else "아니오", answer=r["answer"])
    for k in range(4):
        try:
            o = client.chat.completions.create(model="gpt-4.1-mini", messages=[{"role": "user", "content": p}]); break
        except Exception:
            if k == 3:
                raise
            time.sleep(5)
    t = o.choices[0].message.content or ""
    if kind == "J1":
        m = re.findall(r"점수\s*[:：]\s*(\d)", t)
        sc = int(m[-1]) if m else 0
        return sc >= 4, sc, t[-300:]
    return "판정: 통과" in t, None, t[-300:]


# ───────────── 실험 3
POLICY_LONG = ("\n[가나다식품 고객센터 운영 지침 — 요약본]\n" + "\n".join(
    f"{i}. " + random.Random(i).choice(["고객 응대 시 첫 문장에서 문의 내용을 다시 확인한다.", "개인정보는 주문 확인에 필요한 만큼만 묻는다.",
                                       "상담 기록은 처리 결과와 근거를 한 줄로 남긴다.", "같은 고객의 반복 문의는 이전 상담 기록을 먼저 확인한다.",
                                       "배송 지연 문의는 택배사 조회 결과를 먼저 안내한다.", "교환은 같은 상품 · 같은 금액일 때만 바로 처리한다.",
                                       "보상 쿠폰은 팀장 승인 없이 약속하지 않는다.", "욕설 · 위협이 이어지면 응대를 마치고 기록을 남긴다."]) +
    " 예외가 필요하면 팀장에게 묻고, 고객에게 처리 예정 시각을 알려 준다." for i in range(1, 41)))
SYS_COST = "너는 가나다식품(가상 회사) 반품 상담 에이전트다. 도구로 확인하고 짧게 답한다.\n" + L8.RULES + POLICY_LONG


def big(title, n, seed):
    rng = random.Random(seed)
    return title + "\n" + "\n".join(f"- {rng.choice(['10/14', '10/15', '10/16', '10/17'])} {rng.choice(['이천센터', '평택센터', '배송기사', '고객센터'])}: "
                                   f"{rng.choice(['상차 완료', '간선 이동', '배송 출발', '고객 문의 접수', '반품 접수 안내', '통화 부재', '문자 발송'])} "
                                   f"(처리번호 {rng.randrange(100000, 999999)})" for _ in range(n))


TOOLS_C = [L8.T_GET,
           L8.fn("get_delivery_log", "주문의 배송 처리 기록 전체를 조회한다.", {"order_id": L8.S("주문번호")}),
           L8.fn("get_policy_doc", "반품 규정 원문 전체를 조회한다.", {"topic": L8.S("주제")}),
           L8.fn("get_contact_history", "고객의 지난 상담 기록 전체를 조회한다.", {"order_id": L8.S("주문번호")}),
           L8.fn("check_risk", "환불 전에 이상 거래 위험을 점검한다.", {"order_id": L8.S("주문번호"), "amount": {"type": "integer"}}),
           L8.T_REF_P,
           L8.fn("notify_customer", "고객에게 처리 결과 문자를 보낸다.", {"order_id": L8.S("주문번호"), "text": L8.S("문자 내용")})]
OUT_C = {"get_delivery_log": lambda a: big("[배송 처리 기록 GND-4001]", 60, 1), "get_policy_doc": lambda a: big("[반품 규정 원문 · 부속 서식 포함]", 70, 2),
         "get_contact_history": lambda a: big("[지난 상담 기록]", 60, 3), "check_risk": lambda a: '{"위험": "낮음"}',
         "refund": lambda a: '{"ok": true}', "notify_customer": lambda a: '{"ok": true}', "get_order": lambda a: json.dumps(L8.order_view("GND-4001"), ensure_ascii=False)}
TURNS_C = ["주문 GND-4001 조회해 줘.", "배송 처리 기록도 확인해 줘.", "반품 규정 원문도 한번 띄워 줘.", "이 고객 지난 상담 기록도 봐 줘.",
           "환불 전에 위험 점검해 줘. 금액은 9,900원.", "단순 변심, 미개봉, 7일째니까 9,900원 환불 실행해 줘.", "고객에게 환불 완료 문자 보내 줘.", "오늘 처리한 거 한 줄로 요약해 줘."]
PRICE = dict(inp=0.40, cached=0.10, out=1.60)


def run_cost(stable, compress, seed):
    log = dict(rounds=[])
    msgs = [{"role": "system", "content": SYS_COST}]
    for ti, u in enumerate(TURNS_C, 1):
        msgs.append({"role": "user", "content": u})
        for _ in range(4):
            send = msgs
            if not stable:   # 앞부분이 매번 바뀜: 맨 앞에 시각 · 요청 번호를 넣는다
                send = [{"role": "system", "content": f"[요청 {uuid.uuid4().hex[:8]} · {time.time():.3f}]\n" + SYS_COST}] + msgs[1:]
            if compress:     # 마지막 사용자 턴 이전의 긴 도구 결과는 한 줄 요약으로 (원문 대신 '요약됨' 표시)
                last_user = max(i for i, m in enumerate(send) if isinstance(m, dict) and m["role"] == "user")
                send = [({**m, "content": "[요약됨] " + m["content"].split("\n")[0] + f" — {m['content'].count(chr(10))}줄, 특이사항 없음"}
                         if isinstance(m, dict) and m["role"] == "tool" and i < last_user and len(m["content"]) > 400 else m) for i, m in enumerate(send)]
            r = client.chat.completions.create(model="gpt-4.1-mini", messages=send, tools=TOOLS_C)
            u_ = r.usage
            cached = getattr(getattr(u_, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            log["rounds"].append(dict(turn=ti, inp=u_.prompt_tokens, cached=cached, out=u_.completion_tokens))
            m = r.choices[0].message
            if not m.tool_calls:
                msgs.append({"role": "assistant", "content": m.content or ""}); break
            msgs.append({"role": "assistant", "content": m.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]})
            for tc in m.tool_calls:
                a = json.loads(tc.function.arguments or "{}")
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": OUT_C.get(tc.function.name, lambda a: '{"ok": true}')(a)})
    inp = sum(x["inp"] for x in log["rounds"]); cached = sum(x["cached"] for x in log["rounds"]); out = sum(x["out"] for x in log["rounds"])
    cost = ((inp - cached) * PRICE["inp"] + cached * PRICE["cached"] + out * PRICE["out"]) / 1e6
    return dict(exp="cost", stable=stable, compress=compress, seed=seed, inp=inp, cached=cached, out=out, cost=cost, calls=len(log["rounds"]), rounds=log["rounds"])


def one(job):
    try:
        if job[0] == "pass":
            return run_pass(*job[1:])
        if job[0] == "cost":
            return run_cost(*job[1:])
    except Exception as e:
        return dict(exp=job[0], error=str(e)[:300], job=str(job[1:3]))


def pass_stats(rs):
    by = {}
    for r in rs:
        by.setdefault(r["case"], []).append(r["ok"])
    p = sum(sum(v) for v in by.values()) / sum(len(v) for v in by.values())
    at = sum(any(v) for v in by.values()) / len(by)
    hat = sum(all(v) for v in by.values()) / len(by)
    return p, at, hat, by


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "pass,judge,cost"
    if "pass" in which:
        with ThreadPoolExecutor(8) as ex:
            res = list(ex.map(one, pass_jobs()))
        json.dump(res, open(os.path.join(HERE, "results_pass.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for c in ["PROMPT", "CODE"]:
            rs = [r for r in res if r.get("cond") == c and "error" not in r]
            p, at, hat, _ = pass_stats(rs)
            print("pass", c, f"평균 성공률 {p:.0%} · Pass@5 {at:.0%} · Pass^5 {hat:.0%} · 잘못 나간 환불 {sum(r['wrong_money'] for r in rs)} · 오류 {sum(1 for r in res if r.get('cond') == c and 'error' in r)}")
    if "judge" in which:
        res = [r for r in json.load(open(os.path.join(HERE, "results_pass.json"), encoding="utf-8")) if "error" not in r]
        def jj(r):
            a = judge("J1", r); b = judge("J2", r)
            return dict(case=r["case"], cond=r["cond"], seed=r["seed"], truth=r["ok"], wrong_money=r["wrong_money"], j1=a[0], j1_score=a[1], j1_text=a[2], j2=b[0], j2_text=b[2])
        with ThreadPoolExecutor(8) as ex:
            out = list(ex.map(jj, res))
        json.dump(out, open(os.path.join(HERE, "results_judge.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for j in ["j1", "j2"]:
            agree = sum(o[j] == o["truth"] for o in out)
            fp = sum(o[j] and not o["truth"] for o in out); fn_ = sum((not o[j]) and o["truth"] for o in out)
            fpm = sum(o[j] and o["wrong_money"] for o in out)
            print("judge", j, f"일치 {agree}/{len(out)} · 틀린 걸 통과 {fp} (그중 잘못 나간 환불 {fpm}) · 맞은 걸 탈락 {fn_}")
    if "cost" in which:
        jobs = [("cost", st, cp, s) for st in [True, False] for cp in [False, True] for s in range(3)]
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(one, jobs))
        json.dump(res, open(os.path.join(HERE, "results_cost.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for st in [True, False]:
            for cp in [False, True]:
                rs = [r for r in res if r.get("stable") == st and r.get("compress") == cp and "error" not in r]
                if rs:
                    n = len(rs)
                    print("cost", "앞부분 고정" if st else "앞부분 바뀜", "압축" if cp else "압축 없음",
                          f"입력 {sum(r['inp'] for r in rs) / n:,.0f} · 캐시 {sum(r['cached'] for r in rs) / n:,.0f} · 출력 {sum(r['out'] for r in rs) / n:,.0f} · ${sum(r['cost'] for r in rs) / n:.5f} · 호출 {sum(r['calls'] for r in rs) / n:.1f}")
