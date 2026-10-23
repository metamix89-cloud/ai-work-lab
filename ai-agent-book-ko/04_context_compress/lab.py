# -*- coding: utf-8 -*-
"""ep039 실습 — 대화가 길어지면: 컨텍스트 압축 전략 비교 (원서 2장 실험 2-10 방식, 가나다식품 거래처 상담 하루로 각색).
가나마트(가상) 구매 담당자와 20턴 상담. 중간에 카탈로그 · 재고표 · 공지문 같은 긴 도구 결과가 쌓이고,
대화 곳곳에서 정한 사실 6개를 마지막 '발주 확인서'에 정확히 남기는지 채점한다.
창 한도는 원서처럼 일부러 줄여 BUDGET 토큰으로 둔다(모델 자체 창은 더 크지만, 한도를 넘는 순간 '실패'로 기록).
전략 6개 × 5회 실제 실행 → results.json
  S0 참고: 한도 없음 : 모든 기록 그대로, 창 한도 검사도 하지 않음 (창이 충분히 클 때의 기준)
  S1 압축 없음        : 모든 기록 그대로
  S2 잘라내기         : 최근 8턴만 남기고 앞은 버림
  S3 일반 요약        : 도구 결과가 올 때마다 작업과 상관없이 '3~5문장 요약'으로 바꿈
  S4 작업 인식 요약   : 요약할 때 지금 질문 · 지금까지 대화를 함께 주고 '이후에 필요한 사실' 위주로
  S5 한도 근처 일괄   : 입력이 한도의 80%를 넘을 때만, 아직 안 줄인 도구 결과를 S4 방식으로 한꺼번에
  S6 진행 노트        : S2 처럼 최근 8턴만 남기되, 에이전트가 save_note 로 확정 사항을 노트에 적고 노트는 항상 보임"""
import json, os, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
BUDGET = 32000
WINDOW = 8
TRIALS = 5

# ── 긴 도구 결과 (가상 데이터, 고정 시드)
rng = random.Random(7)
NAMES = {
    "냉동": ["냉동만두 1kg", "떡볶이 밀키트", "어묵탕 세트", "한우 선물세트", "새우볶음밥", "김치볶음밥", "치킨너겟", "돈까스 1kg", "물만두 700g", "감자튀김",
             "군만두 1kg", "왕교자", "갈비만두", "냉동 피자", "핫도그 5입", "닭가슴살 큐브", "부대찌개 키트", "순대 500g", "떡갈비 냉동", "냉동 블루베리"],
    "상온": ["고추장 500g", "참기름 350ml", "들기름 김자반", "된장 1kg", "쌈장 500g", "간장 900ml", "식용유 1.8L", "참깨 200g", "고춧가루 500g", "올리고당",
             "즉석밥 210g", "컵라면 6입", "캔햄 200g", "참치캔 3입", "꿀 500g", "누룽지", "미역 100g", "김 20봉", "볶음밥 소스", "카레 분말"],
    "냉장": ["수제 떡갈비", "두부 2입", "생와사비 소스", "콩나물", "어묵 1kg", "계란 30구", "우유 1L", "요거트 4입", "샐러드 키트", "김치 3kg",
             "깍두기 1kg", "햄 슬라이스", "치즈 슬라이스", "생면 우동", "순두부", "도토리묵", "단무지", "맛살", "베이컨", "소시지"],
    "선물세트": ["명절 선물세트 A", "명절 선물세트 B", "참기름 선물세트", "한우 선물세트 VIP", "김 선물세트", "햄 선물세트", "과일청 세트", "건강즙 세트",
              "견과 세트", "커피 세트", "올리브유 세트", "수산 선물세트", "버섯 세트", "곶감 세트", "한과 세트", "식혜 세트", "홍삼 세트", "조미김 세트", "꿀 세트", "차 세트"],
}


def catalog(cat):
    rng = random.Random(1)
    rows = []
    for i, n in enumerate(NAMES[cat] * 3):
        code = f"GND-{ {'냉동': 'F', '상온': 'A', '냉장': 'C', '선물세트': 'G'}[cat]}{100 + i}".replace(" ", "")
        price = rng.randrange(30, 900) * 100
        rows.append(f"{code} | {n}{'' if i < len(NAMES[cat]) else ' (' + ['대용량', '업소용'][i // len(NAMES[cat]) - 1] + ')'} | 박스당 {rng.choice([6, 8, 10, 12, 20, 24])}입 | "
                    f"정상가 {price:,}원 | 행사가 {int(price * rng.choice([0.85, 0.9, 0.95])):,}원 | 유통기한 {rng.choice(['6개월', '9개월', '12개월', '18개월', '10일', '14일', '30일'])} | "
                    f"보관 {cat} | 원산지 {rng.choice(['국산', '국산/수입 혼합', '수입(미국)', '수입(호주)'])} | 최소주문 {rng.choice([5, 10, 20])}박스 | 비고 {rng.choice(['-', '포장 변경 예정', '신규', '행사 추천', '재고 한정'])}")
    if cat == "냉동":
        rows[0] = "GND-F100 | 냉동만두 1kg | 박스당 10입 | 정상가 52,000원 | 행사가 46,800원 | 유통기한 12개월 | 보관 냉동 | 원산지 국산 | 최소주문 10박스 | 비고 행사 추천"
    return f"[가나다식품 {cat} 제품 카탈로그 2026 하반기]\n코드 | 상품 | 입수 | 정상가 | 행사가 | 유통기한 | 보관 | 원산지 | 최소주문 | 비고\n" + "\n".join(rows)


def stock_report():
    rng = random.Random(2)
    rows = []
    for cat in ["냉동", "상온", "냉장"]:
        for j, n in enumerate(NAMES[cat] * 2):
            n = n if j < len(NAMES[cat]) else n + " (업소용)"
            rows.append(f"{n} | {cat} | 현재고 {rng.randrange(20, 2000)}박스 | 이번 주 출고 {rng.randrange(10, 400)}박스 | 입고 예정 {rng.choice(['10/27', '10/29', '11/3', '11/5', '없음'])} | 상태 {rng.choice(['정상', '정상', '정상', '부족 주의'])}")
    rows[1] = "떡볶이 밀키트 | 냉동 | 현재고 0박스 | 이번 주 출고 0박스 | 입고 예정 11/5 → 11/12로 지연(소스 공급 문제) | 상태 11/12부터 출고 가능"
    return "[물류센터 재고 현황표 · 10/21 09:00 기준]\n품목 | 분류 | 현재고 | 이번 주 출고 | 입고 예정 | 상태\n" + "\n".join(rows)


def delivery_schedule():
    rng = random.Random(3)
    rows = [f"{r} 권역 | {d} | 상온 차량 {rng.choice(['매일', '월수금', '화목'])} | 냉동 차량 {rng.choice(['월수금', '화목', '매일'])} | 마감 {rng.choice(['전날 15시', '전날 17시', '2일 전 15시'])} | 비고 {rng.choice(['-', '공휴일 휴무', '11월 증차'])}"
            for r in ["서울 동부", "서울 서부", "서울 남부", "서울 북부", "인천", "수원", "용인", "성남", "이천", "평택", "천안", "청주", "대전", "세종", "원주", "춘천", "강릉", "전주", "광주", "대구", "부산", "울산", "창원", "제주"]
            for d in ["대형마트", "슈퍼", "온라인몰 센터"]]
    return "[가나다식품 배송 일정표 · 11월]\n권역 | 거래처 유형 | 상온 차량 | 냉동 차량 | 주문 마감 | 비고\n" + "\n".join(rows)


def notice(kind):
    rng = random.Random(4)
    paras = [f"{i}. {rng.choice(['물류비', '포장재', '원재료', '인건비', '환율'])} 변동에 따라 {rng.choice(['일부 품목', '선물세트', '업소용 제품'])}의 "
             f"{rng.choice(['공급 조건', '최소 주문 수량', '포장 단위', '발주 마감 시간'])}이 {rng.choice(['조정', '변경', '검토'])}될 수 있습니다. 자세한 내용은 담당 영업사원에게 문의 바랍니다. "
             f"해당 사항은 {rng.choice(['10월', '11월', '12월'])} {rng.randrange(1, 28)}일 기준으로 적용되며 거래처별 계약 조건에 따라 달라질 수 있습니다." for i in range(1, 46)]
    if kind == "단가":
        paras.insert(27, "28. [중요] 냉동 제품군(냉동만두 · 밀키트 · 어묵탕 등) 공급 단가 3% 인상은 당초 11월 1일 시행 예정이었으나 12월 1일로 연기합니다. "
                         "상온 제품군 인상(2%)은 예정대로 11월 1일 시행합니다.")
        title = "[공지] 2026년 하반기 공급 단가 및 거래 조건 안내"
    else:
        title = "[공지] 거래처 반품 · 교환 처리 기준"
    return title + "\n" + "\n".join(paras)


def sales_history():
    rng = random.Random(5)
    rows = [f"2025 {m}월 | {n} | 판매 {rng.randrange(50, 3000)}박스 | 행사 {rng.choice(['있음', '없음'])} | 반품률 {rng.randrange(0, 40) / 10}%"
            for m in [9, 10, 11, 12] for n in NAMES["냉동"] + NAMES["상온"][:10]]
    return "[가나마트 납품 실적 2025 9~12월]\n" + "\n".join(rows)


TOOL_IMPL = {
    "get_catalog": lambda a: catalog(a.get("category", "냉동") if a.get("category") in NAMES else "냉동"),
    "get_stock_report": lambda a: stock_report(),
    "get_delivery_schedule": lambda a: delivery_schedule(),
    "get_notice": lambda a: notice("반품" if "반품" in a.get("topic", "") else "단가"),
    "get_sales_history": lambda a: sales_history(),
}


def fn(name, d, props):
    return {"type": "function", "function": {"name": name, "description": d, "parameters": {
        "type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()}, "required": list(props)}}}


TOOLS = [fn("get_catalog", "제품 카탈로그 전체를 조회한다.", {"category": "냉동 · 상온 · 냉장 · 선물세트 중 하나"}),
         fn("get_stock_report", "물류센터 전체 재고 현황표를 조회한다.", {}),
         fn("get_delivery_schedule", "권역별 배송 일정표를 조회한다.", {}),
         fn("get_notice", "거래처 공지 문서를 조회한다.", {"topic": "'단가' 또는 '반품'"}),
         fn("get_sales_history", "가나마트 작년 납품 실적을 조회한다.", {})]
T_NOTE = fn("save_note", "오늘 상담에서 확정되거나 바뀐 사항을 진행 노트에 적는다. 노트 전체를 새로 써서 넘긴다(바뀐 내용은 고쳐 쓴다).", {"text": "노트 전체 내용"})

SYS = ("너는 가나다식품(가상 회사) 영업지원 에이전트다. 거래처 가나마트 구매팀 담당자와 하루 종일 대화하며 발주를 돕는다. "
       "자료가 필요하면 도구로 조회한다. 답은 짧게 한다. 모르는 것은 지어내지 않는다.")
SYS_NOTE = ("\n대화가 길어 오래된 대화는 잘려 나간다. 확정되거나 바뀐 사항(수량 · 배송지 · 요일 · 날짜 · 조건)이 생기면 "
            "바로 save_note 로 진행 노트를 갱신한다.")

TURNS = [
    "안녕하세요, 가나마트 구매팀 이 대리입니다. 다음 달 행사 준비 때문에 오늘 하루 이것저것 여쭤볼게요. 먼저 냉동 제품 카탈로그 보여 주세요.",
    "냉동만두 1kg 행사가가 얼마죠?",
    "좋아요. 행사용 냉동만두 1kg 120박스로 확정할게요.",
    "상온 제품 카탈로그도 보여 주세요.",
    "아, 그리고 이번 발주 배송지는 본점 말고 가나마트 2물류센터(경기 이천)로 바꿔 주세요.",
    "냉장 제품 카탈로그도 볼게요.",
    "떡볶이 밀키트 재고 현황 확인해 주세요.",
    "참기름 350ml 는 박스당 몇 개 들어 있어요?",
    "11월 배송 일정표 보여 주세요.",
    "공급 단가 관련 공지 있으면 보여 주세요.",
    "고추장 500g 유통기한은 얼마나 되나요?",
    "결제 조건은 월말 마감, 익월 15일 현금으로 해 주세요.",
    "선물세트 카탈로그도 보여 주세요.",
    "행사 반응이 좋을 것 같아서 냉동만두는 120박스 말고 150박스로 늘려 주세요.",
    "작년 9~12월 저희 납품 실적 자료 있나요?",
    "참, 저희 2물류센터는 냉동 차량을 화요일 · 목요일만 받아요.",
    "어묵탕 세트도 행사에 넣을지 고민인데, 재고 현황 다시 보여 주세요.",
    "음… 어묵탕은 이번엔 빼죠.",
    "반품 규정 공지도 보여 주세요.",
    "오늘 정한 것 전부 반영해서 발주 확인서 써 주세요. 품목 · 수량, 배송지, 냉동 배송 요일, 냉동 단가 인상 적용 시점, 결제 조건, 떡볶이 밀키트 출고 가능일을 꼭 넣어 주세요.",
]

FACTS = [("수량 150박스", lambda t: bool(re.search(r"150\s*박스", t))),
         ("배송지 2물류센터", lambda t: "2물류센터" in t or "이천" in t),
         ("냉동 화 · 목", lambda t: bool(re.search(r"화(요일)?\s*[·,/및와과 ]+\s*목", t))),
         ("단가 인상 12/1", lambda t: bool(re.search(r"12\s*월\s*1\s*일|12/1\b|12\.1\b|12\.\s*1\.", t))),
         ("결제 익월 15일", lambda t: "15일" in t),
         ("밀키트 11/12", lambda t: bool(re.search(r"11\s*월\s*12\s*일|11/12|11\.12", t)))]


def chat(messages, tools=None, log=None, kind="main"):
    kw = dict(model=MODEL, messages=messages)
    if tools:
        kw["tools"] = tools
    for k in range(4):
        try:
            r = client.chat.completions.create(**kw); break
        except Exception as e:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    if log is not None:
        log["tokens_" + kind] += r.usage.prompt_tokens + r.usage.completion_tokens
    return r


def summarize(text, log, task_aware=False, query="", recent=""):
    if task_aware:
        p = (f"너는 영업지원 에이전트의 기록 정리 담당이다. 아래 도구 결과를 줄여라.\n지금 거래처의 질문: {query}\n최근 대화:\n{recent}\n\n"
             "규칙: 이 질문과 앞으로의 발주에 필요한 사실만 남긴다. 숫자 · 날짜 · 변경 사항 · 예외는 원문 그대로 남기고, 관련 없는 행은 버린다. 10줄 이내.\n\n도구 결과:\n" + text)
    else:
        p = "다음 문서를 3~5문장으로 요약하라.\n\n" + text
    r = chat([{"role": "user", "content": p}], log=log, kind="compress")
    return r.choices[0].message.content or ""


def recent_text(messages, n=6):
    out = []
    for m in messages[-n:]:
        role = m["role"] if isinstance(m, dict) else m.role
        c = m.get("content") if isinstance(m, dict) else m.content
        if role in ("user", "assistant") and c:
            out.append(f"{role}: {c[:300]}")
    return "\n".join(out)


def window(messages, turns):
    """최근 turns 개 사용자 턴만 남긴다 (시스템 메시지는 유지)."""
    idx = [i for i, m in enumerate(messages) if isinstance(m, dict) and m["role"] == "user"]
    if len(idx) <= turns:
        return messages
    return [messages[0]] + messages[idx[-turns]:]


def run(strategy, seed):
    log = dict(tokens_main=0, tokens_compress=0, overflow_turn=None, max_prompt=0, notes="", compressions=0, calls=[])
    sys_txt = SYS + (SYS_NOTE if strategy == "S6" else "")
    history = [{"role": "system", "content": sys_txt}]
    tools = TOOLS + ([T_NOTE] if strategy == "S6" else [])
    final = ""
    for ti, user in enumerate(TURNS, 1):
        history.append({"role": "user", "content": user})
        for _ in range(6):
            msgs = history
            if strategy in ("S2", "S6"):
                msgs = window(history, WINDOW)
            if strategy == "S6" and log["notes"]:
                msgs = [{"role": "system", "content": sys_txt + "\n\n[진행 노트]\n" + log["notes"]}] + msgs[1:]
            r = chat(msgs, tools, log)
            pt = r.usage.prompt_tokens
            log["max_prompt"] = max(log["max_prompt"], pt)
            if pt > BUDGET and strategy != "S0":
                log["overflow_turn"] = ti
                return log, ""
            m = r.choices[0].message
            if not m.tool_calls:
                history.append({"role": "assistant", "content": m.content or ""})
                if ti == len(TURNS):
                    final = m.content or ""
                break
            history.append({"role": "assistant", "content": m.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]})
            for tc in m.tool_calls:
                log["calls"].append(f"{ti}:{tc.function.name}")
                try:
                    a = json.loads(tc.function.arguments or "{}")
                except Exception:
                    a = {}
                if tc.function.name == "save_note":
                    log["notes"] = a.get("text", ""); out = "노트 저장됨"; tag = False
                else:
                    out = TOOL_IMPL.get(tc.function.name, lambda a: "오류: 없는 도구")(a); tag = True
                    if strategy == "S3":
                        out = "[COMPRESSED] " + summarize(out, log); log["compressions"] += 1
                    elif strategy == "S4":
                        out = "[COMPRESSED] " + summarize(out, log, True, user, recent_text(history)); log["compressions"] += 1
                history.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            if strategy == "S5" and pt > BUDGET * 0.8:
                for h in history:
                    if isinstance(h, dict) and h["role"] == "tool" and not h["content"].startswith("[COMPRESSED]") and len(h["content"]) > 500:
                        h["content"] = "[COMPRESSED] " + summarize(h["content"], log, True, user, recent_text(history)); log["compressions"] += 1
        else:
            pass
        # S5: 사용자 턴이 끝날 때도 한도 근처면 일괄 압축
        if strategy == "S5" and log["max_prompt"] > BUDGET * 0.8:
            for h in history:
                if isinstance(h, dict) and h["role"] == "tool" and not h["content"].startswith("[COMPRESSED]") and len(h["content"]) > 500:
                    h["content"] = "[COMPRESSED] " + summarize(h["content"], log, True, user, recent_text(history)); log["compressions"] += 1
    return log, final


def one(job):
    s, seed = job
    t0 = time.time()
    try:
        log, final = run(s, seed)
    except Exception as e:
        return dict(strategy=s, seed=seed, error=str(e)[:300])
    kept = [name for name, f in FACTS if f(final)]
    return dict(strategy=s, seed=seed, kept=kept, n_kept=len(kept), overflow_turn=log["overflow_turn"], max_prompt=log["max_prompt"],
                tokens_main=log["tokens_main"], tokens_compress=log["tokens_compress"], compressions=log["compressions"],
                notes=log["notes"][:1500], calls=log["calls"], final=final[:2500], sec=round(time.time() - t0))


if __name__ == "__main__":
    strategies = sys.argv[1].split(",") if len(sys.argv) > 1 else ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    out = sys.argv[3] if len(sys.argv) > 3 else "results.json"
    jobs = [(s, k) for s in strategies for k in range(trials)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, jobs))
    json.dump(res, open(os.path.join(HERE, out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for s in strategies:
        rs = [r for r in res if r["strategy"] == s and "error" not in r]
        print(s, "사실 유지", sum(r["n_kept"] for r in rs), "/", 6 * len(rs), "· 넘침", sum(1 for r in rs if r["overflow_turn"]),
              "· 평균 토큰", round(sum(r["tokens_main"] + r["tokens_compress"] for r in rs) / max(1, len(rs))),
              "· 최대 입력", round(sum(r["max_prompt"] for r in rs) / max(1, len(rs))), "· 오류", sum(1 for r in res if r["strategy"] == s and "error" in r))
