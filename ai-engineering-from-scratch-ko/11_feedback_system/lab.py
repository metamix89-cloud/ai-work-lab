# -*- coding: utf-8 -*-
"""ep057 실습 — 시즌 2 11편: 같은 지적을 두 번 하지 않으려면 (원본 Phase 14 레슨 46 'Turn Every Agent Correction into a System Improvement').
가나다식품(가상) 견적서 작성 AI. 지난 세션에서 팀장이 지적한 3가지(아래 CORR)를 다음 세션들에 어떻게 남기느냐에 따라 재발을 잰다.
새 견적 10건 × 2회 = 조건마다 20건, gpt-4.1-mini.
  A 기록 없음        : 새 세션, 교정 기록 없음
  B 증상 메모        : 팀장이 한 말 그대로 메모 ("떡볶이 소스는 79,270원이야" 등)
  C 원인 규칙        : 원인을 찾아 규칙으로 ("단가는 견적일 기준 적용일이 지난 가장 최근 행" 등)
  D 원인 규칙 + 검사기 : C + 코드 검사기 — 견적이 규칙을 어기면 어느 규칙인지만 알려 주고 한 번 고치게 함
함정: 견적일이 10월인 견적(T3 · T5 · T8)은 옛 단가가 맞다 — 증상 메모('79,270')를 그대로 따르면 틀린다. 2027년 단가 행도 있다.
채점(코드): 품목 단가 정확 · '부가세 포함' 표기 · 유효기간(발행일+14일) 정확."""
import json, os, re, sys, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 2))

PRICES = """[단가표 — 박스 단가, 부가세 포함 가격]
품목,단가,적용일
떡볶이 소스 2kg,73400,2026-07-01
떡볶이 소스 2kg,79270,2026-11-01
떡볶이 소스 2kg,82000,2027-01-01
고추장 500g,46200,2026-07-01
고추장 500g,47500,2026-11-01
된장 1kg,39800,2026-07-01"""
HIST = {"떡볶이 소스 2kg": [("2026-07-01", 73400), ("2026-11-01", 79270), ("2027-01-01", 82000)],
        "고추장 500g": [("2026-07-01", 46200), ("2026-11-01", 47500)], "된장 1kg": [("2026-07-01", 39800)]}

TASKS = [
    ("2026-11-05", "가나마트", [("떡볶이 소스 2kg", 30), ("고추장 500g", 20)]),
    ("2026-11-05", "다나유통", [("된장 1kg", 10), ("떡볶이 소스 2kg", 12)]),
    ("2026-10-25", "라마상회", [("떡볶이 소스 2kg", 5), ("고추장 500g", 5)]),
    ("2026-11-12", "가나마트", [("고추장 500g", 40)]),
    ("2026-10-30", "바사푸드", [("떡볶이 소스 2kg", 8), ("된장 1kg", 4)]),
    ("2026-11-03", "아자식품", [("떡볶이 소스 2kg", 15)]),
    ("2026-11-20", "가나마트", [("된장 1kg", 20), ("고추장 500g", 10)]),
    ("2026-10-28", "다나유통", [("고추장 500g", 12)]),
    ("2026-11-07", "라마상회", [("떡볶이 소스 2kg", 20), ("고추장 500g", 20), ("된장 1kg", 20)]),
    ("2026-11-01", "바사푸드", [("떡볶이 소스 2kg", 10)]),
]

BASE = "너는 가나다식품 영업지원팀의 견적서 작성 AI 다. 단가표를 보고 거래처에 보낼 견적서를 쓴다. 품목마다 수량 · 단가 · 금액을 표로 쓴다."
SYMPTOM = """
[지난번 팀장 지적 — 받은 그대로 메모]
- "떡볶이 소스는 73,400원이 아니라 79,270원이야. 고쳐."
- "금액에 부가세 별도라고 쓰지 마."
- "견적 유효기간 빼먹었어. 넣어.\""""
CAUSE = """
[견적 규칙 — 지난 지적의 원인을 찾아 정리]
1. 단가: 품목마다 단가표에서 '적용일이 견적일 이전(같은 날 포함)인 행 중 가장 최근 행'을 쓴다. 앞으로 적용될 행은 쓰지 않는다.
   (지난번 원인: 적용일을 보지 않고 첫 행을 씀)
2. 우리 단가는 부가세 포함 가격이다. 금액 옆에 '(부가세 포함)'이라고 쓰고, 부가세를 따로 더하지 않는다.
3. 견적 유효기간 = 견적일 + 14일. 견적서 맨 아래에 '유효기간: YYYY-MM-DD 까지'로 쓴다."""
COND = {"A": BASE, "B": BASE + SYMPTOM, "C": BASE + CAUSE, "D": BASE + CAUSE}


def expected_price(item, day):
    rows = [p for d, p in HIST[item] if d <= day]
    return rows[-1]


def check(task, rep):
    day, cust, items = task
    fails = []
    price_ok = 0
    for item, qty in items:
        want = expected_price(item, day)
        lines = [l for l in rep.splitlines() if item.split()[0] in l.replace(" ", "") or item.split()[0] in l]
        nums = {int(x.replace(",", "")) for l in lines for x in re.findall(r"\d{1,3}(?:,\d{3})+|\d{4,}", l)}
        if want in nums and not ({p for _, p in HIST[item]} - {want}) & nums:
            price_ok += 1
        else:
            fails.append("단가: %s" % item)
    vat = bool(re.search(r"부가세\s*포함", rep)) and not re.search(r"부가세\s*별도|VAT\s*별도|부가세\s*\(?10%\)?\s*[:：]?\s*[\d,]+원", rep)
    if not vat:
        fails.append("부가세 표기")
    valid_day = (dt.date.fromisoformat(day) + dt.timedelta(days=14)).isoformat()
    m = re.search(r"유효\s*기간[^\n]*", rep)
    valid = bool(m) and (valid_day in m.group(0) or valid_day.replace("-", ".") in m.group(0) or
                         "%d월 %d일" % (int(valid_day[5:7]), int(valid_day[8:])) in m.group(0))
    if not valid:
        fails.append("유효기간")
    return dict(price_ok=price_ok, n_items=len(items), vat=vat, valid=valid, fails=fails, ok=not fails)


def ask(sysmsg, user, extra=None):
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}] + (extra or [])
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=0.7)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception:
            time.sleep(3 + 3 * k)
    raise RuntimeError("API 실패")


def run(cond, ti, trial):
    task = TASKS[ti]
    day, cust, items = task
    user = "%s\n\n견적일: %s\n거래처: %s\n품목: %s\n견적서를 써 줘." % (PRICES, day, cust, ", ".join("%s %d박스" % (i, q) for i, q in items))
    rep, tok = ask(COND[cond], user)
    first = check(task, rep)
    retried = False
    if cond == "D" and not first["ok"]:
        # 검사기: 어떤 규칙을 어겼는지만 알려 준다(정답 값은 주지 않음)
        msg = "검사기 결과 — 규칙 위반: " + ", ".join(first["fails"]) + ". 견적 규칙을 다시 확인해 견적서를 고쳐 써 줘."
        rep2, tok2 = ask(COND[cond], user, [{"role": "assistant", "content": rep}, {"role": "user", "content": msg}])
        rep, tok, retried = rep2, tok + tok2, True
    g = check(task, rep)
    return dict(cond=cond, task=ti, trial=trial, report=rep, tokens=tok, retried=retried, first_ok=first["ok"], **g)


def summary(rs):
    for c in "ABCD":
        x = [r for r in rs if r["cond"] == c]
        if not x:
            continue
        old = [r for r in x if TASKS[r["task"]][0] < "2026-11-01"]
        print(c, "완벽 %d/%d" % (sum(r["ok"] for r in x), len(x)),
              "| 단가 맞음 %d/%d" % (sum(r["price_ok"] for r in x), sum(r["n_items"] for r in x)),
              "| 10월 견적(옛 단가) 맞음 %d/%d" % (sum(r["price_ok"] for r in old), sum(r["n_items"] for r in old)),
              "| 부가세 표기 %d" % sum(r["vat"] for r in x), "| 유효기간 %d" % sum(r["valid"] for r in x),
              "| (D: 검사기 전 완벽 %d)" % sum(r["first_ok"] for r in x) if c == "D" else "",
              "| 토큰 %d" % (sum(r["tokens"] for r in x) / len(x)))


if __name__ == "__main__":
    conds = sys.argv[1:] or list(COND)
    jobs = [(c, t, k) for c in conds for t in range(len(TASKS)) for k in range(TRIALS)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda a: run(*a), jobs))
    out = os.path.join(HERE, "results.json")
    old = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    old = [r for r in old if r["cond"] not in conds] + res
    json.dump(old, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summary(old)
