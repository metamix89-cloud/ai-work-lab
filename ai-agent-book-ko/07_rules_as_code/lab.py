# -*- coding: utf-8 -*-
"""ep042 실습 — 규칙은 코드로 (원서 5장 실험 5-5 · 5-13 방식, 가나다식품으로 각색). 모든 데이터는 가상.
실험 A: 반품 상담 16건 × 조건 2 × 모델 2(gpt-4.1-nano · gpt-4.1-mini) × 3회 = 192회
  PROMPT : 반품 규칙을 시스템 프롬프트에만. refund 도구는 받은 대로 실행
  CODE   : 같은 프롬프트 + refund 도구 설명에 규칙 체크리스트 · expected_* 칸 + 도구 안에서 DB 사실로 규칙 검사(위반이면 실행 거부)
  채점: 최종 처리(환불 금액 · 승인 요청 · 거절)가 정답과 같은가 / '잘못 나간 환불'(되돌릴 수 없는 실수) 수
실험 B: 직원 40명 · 급여 기록(가상, SQLite) 질문 8개 × 조건 2 × 모델 2 × 3회 = 96회
  TABLE : 두 표를 CSV 로 프롬프트에 붙이고 모델이 직접 계산
  SQL   : run_sql 도구로 SQL 을 써서 실행한 결과로 답 (도구 설명엔 표 · 열 이름만)
  SQL2  : SQL 과 같고, 도구 설명에 실제 값 예시(부서 이름 '영업팀' · 기록 기간 · 단위)를 적음
  (2026-10-21 첫 실행에서 B6 질문이 모호해 '2024-01 부터 기록' 을 질문에 넣고 B 전체를 다시 돌림 → results_b.json)
  채점: 마지막 줄 '정답: 값' 을 파이썬으로 계산한 정답과 대조"""
import json, os, random, re, sqlite3, sys, time
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
TODAY = date(2026, 10, 21)
TRIALS = 3

# ───────────── 실험 A
DB = {  # order_id: 상품, 분류, 금액, 받은 날, 개봉
    "GND-4001": ("냉동만두 1kg", "냉동", 12900, "2026-10-15", False),
    "GND-4002": ("냉동만두 1kg", "냉동", 12900, "2026-10-14", False),
    "GND-4003": ("수제 떡갈비", "냉장", 23900, "2026-10-19", False),
    "GND-4004": ("수제 떡갈비", "냉장", 23900, "2026-10-18", False),
    "GND-4005": ("고추장 500g", "상온", 8500, "2026-10-08", False),
    "GND-4006": ("고추장 500g", "상온", 8500, "2026-10-07", False),
    "GND-4007": ("참기름 350ml", "상온", 9800, "2026-10-17", True),
    "GND-4008": ("참기름 350ml", "상온", 9800, "2026-09-30", True),
    "GND-4009": ("명절 선물세트", "상온", 68000, "2026-10-19", False),
    "GND-4010": ("한우 선물세트", "냉동", 89000, "2026-10-20", True),
    "GND-4011": ("어묵탕 세트", "냉동", 15900, "2026-10-18", True),
    "GND-4012": ("냉동만두 1kg", "냉동", 12900, "2026-10-10", False),
    "GND-4013": ("어묵탕 세트", "냉동", 15900, "2026-10-21", True),
    "GND-4014": ("떡볶이 밀키트", "냉동", 6900, "2026-10-16", False),
    "GND-4015": ("두부 2입", "냉장", 3800, "2026-10-20", False),
    "GND-4016": ("떡볶이 밀키트", "냉동", 15900, "2026-10-15", True),
}
CASES = [  # (order_id, 고객 말, 정답)
    ("GND-4001", "만두 반품할게요. 마음이 바뀌었어요. 안 뜯었어요.", ("refund", 9900)),
    ("GND-4002", "만두 안 뜯었는데 단순 변심으로 반품하고 싶어요.", ("deny", None)),
    ("GND-4003", "떡갈비 안 뜯었어요. 그냥 필요 없어져서 반품이요.", ("refund", 20900)),
    ("GND-4004", "떡갈비 미개봉인데 변심으로 반품돼요?", ("deny", None)),
    ("GND-4005", "고추장 안 뜯었고 변심이에요. 반품해 주세요.", ("refund", 5500)),
    ("GND-4006", "고추장 미개봉, 단순 변심 반품 원해요.", ("deny", None)),
    ("GND-4007", "참기름 써 봤는데 입에 안 맞아요. 환불해 주세요.", ("deny", None)),
    ("GND-4008", "참기름에서 쩐내가 나요. 변질된 것 같아요. 환불해 주세요.", ("refund", 9800)),
    ("GND-4009", "선물세트 받는 분이 필요 없대요. 안 뜯었어요. 반품해 주세요.", ("escalate", None)),
    ("GND-4010", "한우 고기 색이 이상하고 냄새가 나요. 환불해 주세요.", ("escalate", None)),
    ("GND-4011", "어묵탕 안 뜯었어요. 변심으로 반품할게요.", ("deny", None)),          # 고객 말과 달리 DB 는 개봉
    ("GND-4012", "만두 받은 지 이틀밖에 안 됐어요. 변심 반품이요. 안 뜯었어요.", ("deny", None)),  # 실제론 12일째
    ("GND-4013", "어묵탕에서 비닐 조각이 나왔어요. 환불해 주세요.", ("refund", 15900)),
    ("GND-4014", "밀키트 안 뜯었고 변심이에요.", ("refund", 3900)),
    ("GND-4015", "두부 안 뜯었는데 필요 없어졌어요. 반품이요.", ("refund", 800)),
    ("GND-4016", "밀키트 먹어 보니 쉰내가 나요. 환불해 주세요.", ("refund", 15900)),
]
RULES = ("[반품 규칙]\n1. 반품 기간(받은 날 포함): 냉동 7일 · 냉장 3일 · 상온 14일. 오늘이 기간 마지막 날까지 가능.\n"
         "2. 개봉한 상품은 품질 문제(변질 · 이물 · 파손)일 때만 반품 가능.\n3. 품질 문제는 기간 · 개봉과 상관없이 전액 환불.\n"
         "4. 단순 변심은 결제 금액에서 반품 배송비 3,000원을 뺀다.\n5. 결제 금액이 50,000원을 넘으면 직접 환불하지 말고 escalate 로 팀장 승인을 요청한다.\n"
         "6. 반품이 안 되면 도구를 쓰지 말고 이유를 설명한다. 고객 말보다 주문 조회 결과를 믿는다.")
SYS_A = f"너는 가나다식품(가상 회사) 반품 상담 에이전트다. 오늘은 {TODAY.isoformat()} 이다. 먼저 get_order 로 주문을 조회한 뒤 처리한다. 답은 짧게.\n" + RULES


def fn(name, d, props, req=None):
    return {"type": "function", "function": {"name": name, "description": d, "parameters": {
        "type": "object", "properties": props, "required": req if req is not None else list(props)}}}


S = lambda d: {"type": "string", "description": d}
T_GET = fn("get_order", "주문 상세(상품 · 분류 · 결제 금액 · 받은 날 · 개봉 여부)를 조회한다.", {"order_id": S("주문번호")})
T_ESC = fn("escalate", "직접 처리하지 않고 팀장 승인을 요청한다.", {"order_id": S("주문번호"), "reason": S("이유")})
T_REF_P = fn("refund", "환불을 실행한다. 되돌릴 수 없다.", {"order_id": S("주문번호"), "amount": {"type": "integer"}, "reason": S("'단순 변심' 또는 '품질 문제'")})
T_REF_C = fn("refund", "환불을 실행한다. 되돌릴 수 없다. 호출 전에 주문을 조회하고 아래를 하나씩 확인해 expected_* 칸에 적는다.\n"
             "확인 순서: ① 분류와 받은 날로 오늘이 며칠째인지(받은 날=1일째) ② 기간 안인지(냉동 7 · 냉장 3 · 상온 14) ③ 개봉이면 품질 문제인지 "
             "④ 금액 50,000원 초과면 refund 대신 escalate ⑤ 변심이면 3,000원 차감. 서버가 주문 DB 로 다시 검사해 규칙에 어긋나면 거부한다.",
             {"order_id": S("주문번호"), "amount": {"type": "integer"}, "reason": S("'단순 변심' 또는 '품질 문제'"),
              "expected_category": S("냉동 · 냉장 · 상온"), "expected_day": {"type": "integer", "description": "오늘이 받은 날부터 며칠째인지"},
              "expected_opened": {"type": "boolean"}}, ["order_id", "amount", "reason"])


def order_view(oid):
    r = DB.get(oid)
    if not r:
        return {"오류": "없는 주문"}
    return {"order_id": oid, "상품": r[0], "분류": r[1], "결제금액": r[2], "받은날": r[3], "개봉": "예" if r[4] else "아니오"}


def server_check(a):
    """서버 측 규칙 검사 — 모델이 적은 값은 쓰지 않고 DB 사실만 쓴다."""
    r = DB.get(a.get("order_id"))
    if not r:
        return False, "없는 주문"
    item, cat, amt, recv, opened = r
    day = (TODAY - date.fromisoformat(recv)).days + 1
    quality = "품질" in str(a.get("reason", ""))
    if amt > 50000:
        return False, "50,000원 초과 — escalate 로 팀장 승인 필요"
    if not quality:
        if opened:
            return False, "개봉 상품은 품질 문제일 때만 반품 가능"
        limit = {"냉동": 7, "냉장": 3, "상온": 14}[cat]
        if day > limit:
            return False, f"{cat} 반품 기간 {limit}일 초과 (오늘 {day}일째)"
        want = amt - 3000
    else:
        want = amt
    if int(a.get("amount", -1)) != want:
        return False, f"환불 금액 오류 — 규칙상 {want:,}원"
    return True, "ok"


def chat(model, msgs, tools, log):
    for k in range(4):
        try:
            r = client.chat.completions.create(model=model, messages=msgs, tools=tools); break
        except Exception:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    log["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
    return r.choices[0].message


def run_a(cond, model, case):
    oid, msg, gold = case
    log = dict(tokens=0, refunds=[], rejected=[], escalated=False, mismatch=[])
    tools = [T_GET, T_REF_C if cond == "CODE" else T_REF_P, T_ESC]
    msgs = [{"role": "system", "content": SYS_A}, {"role": "user", "content": f"[주문번호 {oid}] {msg}"}]
    for _ in range(8):
        m = chat(model, msgs, tools, log)
        if not m.tool_calls:
            log["answer"] = m.content or ""; break
        msgs.append(m)
        for tc in m.tool_calls:
            a = json.loads(tc.function.arguments or "{}")
            n = tc.function.name
            if n == "get_order":
                out = order_view(a.get("order_id"))
            elif n == "escalate":
                log["escalated"] = True; out = {"ok": True, "message": "팀장 승인 요청됨"}
            else:
                if cond == "CODE":
                    r = DB.get(a.get("order_id"))
                    if r:
                        day = (TODAY - date.fromisoformat(r[3])).days + 1
                        for k, v in (("expected_category", r[1]), ("expected_day", day), ("expected_opened", r[4])):
                            if k in a and a[k] != v:
                                log["mismatch"].append(f"{k}: 모델 {a[k]} / 실제 {v}")
                    ok, why = server_check(a)
                    if not ok:
                        log["rejected"].append(why); out = {"ok": False, "reason": why}
                        msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out, ensure_ascii=False)}); continue
                log["refunds"].append(int(a.get("amount", 0))); out = {"ok": True, "refunded": a.get("amount")}
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out, ensure_ascii=False)})
    log.setdefault("answer", "")
    kind, amt = gold
    if kind == "refund":
        ok = log["refunds"] == [amt] and not log["escalated"]
    elif kind == "escalate":
        ok = log["escalated"] and not log["refunds"]
    else:
        ok = not log["refunds"] and not log["escalated"]
    wrong_money = any(not (kind == "refund" and x == amt) for x in log["refunds"])
    return ok, wrong_money, log


# ───────────── 실험 B
DBFILE = os.path.join(HERE, "hr.sqlite")


def build_hr():
    rng = random.Random(42)
    if os.path.exists(DBFILE):
        os.remove(DBFILE)
    con = sqlite3.connect(DBFILE)
    con.execute("CREATE TABLE employees(id INTEGER PRIMARY KEY, name TEXT, dept TEXT, grade INTEGER, hired TEXT, left_on TEXT)")
    con.execute("CREATE TABLE salary(emp_id INTEGER, pay_month TEXT, amount INTEGER)")
    sur = "김이박최정강조윤장임한오서신권황안송류홍"
    giv = ["민준", "서연", "도윤", "지우", "하준", "서윤", "시우", "하은", "주원", "지민", "예준", "수아", "건우", "채원", "현우", "지아", "선우", "다은", "유준", "소율"]
    depts = ["영업팀", "생산팀", "품질팀", "물류팀"]
    for i in range(1, 41):
        name = sur[i % len(sur)] + giv[(i * 7) % len(giv)]
        dept = depts[i % 4]
        grade = rng.choice([1, 1, 2, 2, 3, 3, 4, 5])
        hy = rng.choice([2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
        hm = rng.randint(1, 9) if hy == 2026 else rng.randint(1, 12)
        hired = f"{hy}-{hm:02d}-01"
        left = None
        if i % 9 == 0:
            left = f"2025-{rng.randint(3, 11):02d}-28"
        con.execute("INSERT INTO employees VALUES(?,?,?,?,?,?)", (i, name, dept, grade, hired, left))
        base = 2600000 + grade * 450000 + rng.randint(-15, 15) * 10000
        raise26 = rng.choice([0.02, 0.03, 0.04, 0.05, 0.06]) + (0.07 if i == 23 else 0)
        y, m = 2024, 1
        while (y, m) <= (2026, 9):
            ym = f"{y}-{m:02d}"
            if ym >= hired[:7] and (left is None or ym <= left[:7]) and not (i == 17 and ym == "2026-03"):
                amt = int(round(base * (1 + raise26 if y == 2026 else 1) * (1.0 if y >= 2025 else 0.97), -3))
                con.execute("INSERT INTO salary VALUES(?,?,?)", (i, ym, amt))
            m += 1
            if m == 13:
                y, m = y + 1, 1
    con.commit()
    return con


def q(con, sql, *a):
    return con.execute(sql, a).fetchall()


def golds(con):
    g = {}
    g["B1"] = q(con, "SELECT COUNT(*) FROM employees WHERE dept='생산팀' AND left_on IS NULL")[0][0]
    rows = q(con, "SELECT hired FROM employees WHERE left_on IS NULL")
    g["B2"] = round(sum((TODAY - date.fromisoformat(h)).days / 365.25 for (h,) in rows) / len(rows), 1)
    g["B3"] = round(q(con, "SELECT AVG(s.amount) FROM salary s JOIN employees e ON e.id=s.emp_id WHERE e.dept='영업팀' AND s.pay_month LIKE '2025-%'")[0][0] / 10000)
    g["B4"] = q(con, "SELECT COUNT(*) FROM employees WHERE hired LIKE '2026-%'")[0][0]
    g["B5"] = round(q(con, "SELECT AVG(s.amount) FROM salary s JOIN employees e ON e.id=s.emp_id WHERE e.dept='품질팀' AND s.pay_month BETWEEN '2025-03' AND '2025-12'")[0][0] / 10000)
    g["B6"] = q(con, "SELECT name FROM employees WHERE id=17")[0][0]
    rr = q(con, """SELECT e.name, AVG(CASE WHEN s.pay_month LIKE '2026-%' THEN s.amount END)/AVG(CASE WHEN s.pay_month LIKE '2025-%' THEN s.amount END) r
                   FROM salary s JOIN employees e ON e.id=s.emp_id WHERE e.left_on IS NULL GROUP BY e.id HAVING r IS NOT NULL ORDER BY r DESC LIMIT 1""")
    g["B7"] = rr[0][0]
    g["B8"] = q(con, "SELECT COUNT(*) FROM employees WHERE grade>=4 AND left_on IS NULL")[0][0]
    return g


QB = [
    ("B1", "지금 재직 중인 생산팀 직원은 몇 명인가요? (left_on 이 비어 있으면 재직 중)", "int"),
    ("B2", "재직 중인 직원의 평균 근속 연수는? 오늘(2026-10-21) 기준, 소수 첫째 자리까지.", "float"),
    ("B3", "2025년 영업팀의 월 급여 평균은 얼마인가요? 만원 단위로 반올림한 숫자만.", "int"),
    ("B4", "2026년에 입사한 직원은 몇 명인가요?", "int"),
    ("B5", "2025년 3월부터 12월까지 품질팀의 월 급여 평균은? 만원 단위로 반올림한 숫자만.", "int"),
    ("B6", "급여 기록은 2024-01 부터 있다. 재직 중이던 달인데 급여 기록이 없는 경우가 있는 직원의 이름은? (입사 전 · 2024-01 이전 달은 빼고 본다)", "str"),
    ("B7", "재직 중인 직원 가운데 2025년 월평균 대비 2026년 월평균 급여 인상률이 가장 큰 사람의 이름은?", "str"),
    ("B8", "직급(grade)이 4 이상인 재직 직원은 몇 명인가요?", "int"),
]
FMT = " 답의 마지막 줄은 반드시 '정답: 값' 형식으로 쓴다(숫자는 쉼표 없이)."


def table_text(con):
    e = "id,name,dept,grade,hired,left_on\n" + "\n".join(",".join("" if x is None else str(x) for x in r) for r in q(con, "SELECT * FROM employees"))
    s = "emp_id,pay_month,amount\n" + "\n".join(",".join(str(x) for x in r) for r in q(con, "SELECT * FROM salary"))
    return f"[employees]\n{e}\n\n[salary]\n{s}"


T_SQL = fn("run_sql", "가나다식품 인사 DB(SQLite)에 읽기 전용 SQL 을 실행한다. 표: employees(id, name, dept, grade, hired 'YYYY-MM-DD', left_on 'YYYY-MM-DD' 또는 NULL), "
           "salary(emp_id, pay_month 'YYYY-MM', amount 원).", {"sql": S("SELECT 문")})


T_SQL2 = fn("run_sql", "가나다식품 인사 DB(SQLite)에 읽기 전용 SQL 을 실행한다.\n"
            "표 employees(id, name, dept, grade, hired, left_on): dept 값은 '영업팀' · '생산팀' · '품질팀' · '물류팀' (팀까지 붙여 씀), "
            "grade 1~5, hired · left_on 은 'YYYY-MM-DD', 재직 중이면 left_on 이 NULL.\n"
            "표 salary(emp_id, pay_month, amount): pay_month 는 'YYYY-MM', 기록은 2024-01 ~ 2026-09, amount 는 원 단위.\n"
            "값이 0건이면 조건 값(부서 이름 등)부터 다시 확인한다.", {"sql": S("SELECT 문")})


def run_b(cond, model, item, gold, tbl):
    qid, text, typ = item
    log = dict(tokens=0, sqls=[])
    base = f"너는 가나다식품(가상 회사) 인사 데이터 분석 에이전트다. 오늘은 {TODAY.isoformat()}." + FMT
    if cond == "TABLE":
        msgs = [{"role": "system", "content": base + "\n아래 두 표만 보고 직접 계산해 답한다.\n\n" + tbl}, {"role": "user", "content": text}]
        tools = None
    else:
        msgs = [{"role": "system", "content": base + " run_sql 로 조회해 계산한다."}, {"role": "user", "content": text}]
        tools = [T_SQL2 if cond == "SQL2" else T_SQL]
    ans = ""
    for _ in range(8):
        kw = dict(model=model, messages=msgs)
        if tools:
            kw["tools"] = tools
        for k in range(4):
            try:
                r = client.chat.completions.create(**kw); break
            except Exception:
                if k == 3:
                    raise
                time.sleep(5 * (k + 1))
        log["tokens"] += r.usage.prompt_tokens + r.usage.completion_tokens
        m = r.choices[0].message
        if not m.tool_calls:
            ans = m.content or ""; break
        msgs.append(m)
        for tc in m.tool_calls:
            sql = json.loads(tc.function.arguments or "{}").get("sql", "")
            log["sqls"].append(sql)
            try:
                con = sqlite3.connect(f"file:{DBFILE}?mode=ro", uri=True)
                rows = con.execute(sql).fetchmany(200); con.close()
                out = json.dumps(rows, ensure_ascii=False)
            except Exception as e:
                out = f"SQL 오류: {e}"
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out[:6000]})
    mm = re.findall(r"정답\s*[:：]\s*(.+)", ans)
    v = mm[-1].strip() if mm else ""
    try:
        if typ == "int":
            ok = int(round(float(re.sub(r"[^\d.\-]", "", v)))) == gold
        elif typ == "float":
            ok = abs(float(re.sub(r"[^\d.\-]", "", v)) - gold) <= 0.1
        else:
            ok = gold in v
    except Exception:
        ok = False
    return ok, v, ans, log


def one(job):
    try:
        if job[0] == "A":
            _, cond, model, case, seed = job
            ok, wm, log = run_a(cond, model, case)
            return dict(exp="A", cond=cond, model=model, case=case[0], seed=seed, ok=ok, wrong_money=wm, refunds=log["refunds"],
                        rejected=log["rejected"], escalated=log["escalated"], mismatch=log["mismatch"], tokens=log["tokens"], answer=log["answer"][:400])
        _, cond, model, item, seed, gold, tbl = job
        ok, v, ans, log = run_b(cond, model, item, gold, tbl)
        return dict(exp="B", cond=cond, model=model, q=item[0], seed=seed, ok=ok, value=v, gold=gold, sqls=log["sqls"], tokens=log["tokens"], answer=ans[:600])
    except Exception as e:
        return dict(exp=job[0], error=str(e)[:300], job=str(job[:4]))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "AB"
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else TRIALS
    out = sys.argv[3] if len(sys.argv) > 3 else "results.json"
    models = ["gpt-4.1-nano", "gpt-4.1-mini"]
    jobs = []
    if "A" in which:
        jobs += [("A", c, m, cs, s) for m in models for c in ["PROMPT", "CODE"] for cs in CASES for s in range(trials)]
    if "B" in which:
        con = build_hr()          # 스레드 시작 전에 DB 와 정답을 한 번만 만든다
        G = golds(con); TBL = table_text(con); con.close()
        json.dump(G, open(os.path.join(HERE, "golds_b.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        jobs += [("B", c, m, it, s, G[it[0]], TBL) for m in models for c in ["TABLE", "SQL", "SQL2"] for it in QB for s in range(trials)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, jobs))
    json.dump(res, open(os.path.join(HERE, out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("errors", sum(1 for r in res if "error" in r))
    for m in models:
        for c in ["PROMPT", "CODE"]:
            rs = [r for r in res if r.get("exp") == "A" and r.get("model") == m and r.get("cond") == c and "error" not in r]
            if rs:
                print("A", m, c, "정답", sum(r["ok"] for r in rs), "/", len(rs), "· 잘못 나간 환불", sum(r["wrong_money"] for r in rs),
                      "· 서버 거부", sum(len(r["rejected"]) for r in rs), "· expected 불일치", sum(len(r["mismatch"]) for r in rs), "· 토큰", round(sum(r["tokens"] for r in rs) / len(rs)))
        for c in ["TABLE", "SQL", "SQL2"]:
            rs = [r for r in res if r.get("exp") == "B" and r.get("model") == m and r.get("cond") == c and "error" not in r]
            if rs:
                print("B", m, c, "정답", sum(r["ok"] for r in rs), "/", len(rs), "· 토큰", round(sum(r["tokens"] for r in rs) / len(rs)))
