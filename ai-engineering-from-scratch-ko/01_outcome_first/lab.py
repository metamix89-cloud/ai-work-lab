# -*- coding: utf-8 -*-
"""ep047 실습 — 시즌 2 1편: 결과물 말고 성과부터 (원본 Phase 14 레슨 47 'Outcomes before output' · 6칸 성과 틀).
가나다식품(가상) 물류팀 재고표 26품목(기준일 2026-10-26 월). 다음 입고 전에 재고가 바닥나는 품목 6개가 정답.
조건 (gpt-4.1-mini, 각 10회):
  A 결과물만    : "주간 재고 보고서 만들어 줘"
  B 결과물+정성 : A + "팀장님 보고용이니 꼼꼼하고 보기 좋게"
  C 성과 틀     : 사용자 · 상황 · 지금 방식 · 바라는 성과 · 제약 · 비목표 (6칸)
  E 성과 틀 + 확인 방법 : C + "품목마다 버티는 날 수와 입고까지 남은 날 수를 나란히" (레슨의 '증거 질문')
  D 먼저 묻기   : A + "시작 전에 필요한 걸 먼저 물어봐도 된다" → 팀장 역할 모델이 숨은 사정(성과 틀 내용)으로 답한 뒤 작성
채점(코드): 위험 품목 찾음(6) · 잘못 표시 · 단가 노출 · 비목표(매출 · 그래프 · 유통기한) 섞임 · 글자 수.
  '표시'= 품목명이 결품 · 부족 · 위험 등 말과 같은 줄에 나옴(부정 '없음 · 안전 · 충분' 줄 제외). test_grade.py 로 먼저 시험."""
import datetime as dt, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))
TODAY = dt.date(2026, 10, 26)

# 코드, 품목, 센터, 현재고(박스), 일평균 출고(박스), 다음 입고 예정, 매입단가(원/박스), 유통기한 30일 이내(박스)
ROWS = [
    ("F101", "냉동만두 1kg", "이천", 0, 85, "10-28", 41200, 0),
    ("F102", "냉동 김말이 1kg", "이천", 40, 38, "10-29", 38900, 0),
    ("F103", "냉동 떡갈비 500g", "이천", 610, 72, "11-05", 52300, 12),
    ("F104", "냉동 새우볶음밥", "이천", 220, 20, "11-02", 44800, 0),
    ("F105", "냉동 군만두 2kg", "이천", 95, 9, "10-30", 61500, 0),
    ("C201", "두부 300g", "평택", 180, 64, "10-27", 16800, 40),
    ("C202", "생면 칼국수", "평택", 300, 55, "11-03", 22400, 25),
    ("C203", "어묵탕 세트", "평택", 130, 15, "10-31", 33600, 0),
    ("C204", "떡볶이 떡 1kg", "평택", 90, 40, "10-27", 27900, 10),
    ("C205", "순두부 350g", "평택", 260, 30, "11-01", 17500, 30),
    ("D301", "고추장 500g", "서울", 600, 35, "11-09", 46200, 0),
    ("D302", "된장 1kg", "서울", 210, 12, "11-06", 39800, 0),
    ("D303", "간장 1.8L", "서울", 190, 22, "11-02", 54100, 0),
    ("D304", "참기름 320ml", "서울", 400, 18, "11-12", 88600, 0),
    ("D305", "떡볶이 소스 2kg", "서울", 55, 4, "11-05", 73400, 0),
    ("D306", "김자반 50g", "서울", 700, 60, "11-05", 25200, 0),
    ("D307", "컵라면 볶음", "서울", 1500, 140, "11-07", 19800, 0),
    ("D308", "식용유 1.8L", "서울", 160, 25, "10-31", 49900, 0),
    ("M401", "밀키트 부대찌개", "이천", 100, 11, "11-02", 58700, 8),
    ("M402", "밀키트 밀푀유나베", "이천", 150, 26, "11-04", 64300, 0),
    ("M403", "밀키트 닭갈비", "이천", 60, 12, "10-29", 57200, 6),
    ("M404", "밀키트 감바스", "이천", 250, 14, "11-09", 69900, 0),
    ("S501", "견과 선물세트", "서울", 330, 6, "11-20", 95000, 0),
    ("S502", "김 선물세트", "서울", 140, 8, "11-09", 72000, 0),
    ("S503", "한우 사골곰탕", "서울", 70, 7, "11-02", 81500, 0),
    ("S504", "홍삼 젤리", "서울", 500, 9, "11-25", 99000, 0),
]


def arrive_days(a):
    return (dt.date(2026, int(a[:2]), int(a[3:])) - TODAY).days


RISK = {r[0] for r in ROWS if r[3] / r[4] < arrive_days(r[5])}
for r in ROWS:   # 경계가 애매한 품목이 없게: 소진일과 입고일 차이 1일 이상
    assert abs(r[3] / r[4] - arrive_days(r[5])) >= 1, r

TABLE = "기준일: 2026-10-26(월)\n코드\t품목\t센터\t현재고(박스)\t일평균 출고(박스)\t다음 입고 예정\t매입단가(원/박스)\t유통기한 30일 이내(박스)\n" + \
        "\n".join("\t".join(str(x) for x in r) for r in ROWS)

REQ = "이번 주 재고 데이터야. 이걸로 주간 재고 보고서 만들어 줘.\n\n" + TABLE
POLISH = "\n\n팀장님 보고용이니까 꼼꼼하고 보기 좋게 만들어 줘."
FRAME = """이번 주 재고 데이터야. 아래 틀에 맞게 정리해 줘.

[사용자] 물류팀장
[상황] 매주 월요일 9시 발주 회의. 보고서를 회의 화면에 띄우고, 협력 운송사 담당자도 함께 본다.
[지금 방식] 팀장이 엑셀 26줄을 직접 훑으며 날짜를 계산한다. 20분쯤 걸리고 가끔 놓친다(지난달 냉동만두 결품).
[바라는 성과] 회의 시작 5분 안에, 다음 입고 전에 재고가 바닥나는 품목을 빠짐없이 알고 발주를 정한다.
[제약] 매입단가는 회의 자료에 넣지 않는다(운송사 담당자도 봄). 화면 한 장 분량.
[비목표] 매출 분석 · 그래프 · 유통기한 관리(별도 회의에서 다룸).

""" + TABLE
EVID = FRAME.replace("[비목표]", "[확인 방법] 팀장이 회의 중에 바로 검산할 수 있게, 품목마다 '지금 재고로 버티는 날 수(현재고 ÷ 일평균 출고)'와 '다음 입고까지 남은 날 수'를 나란히 보여 주고, 버티는 날 수가 더 짧은 품목에 '결품 위험'이라고 표시해 맨 위에 모은다.\n[비목표]")
ASK = REQ + "\n\n시작하기 전에 꼭 필요한 게 있으면 먼저 물어봐도 돼."
MANAGER = """너는 가나다식품 물류팀장이다. AI가 보고서 작성 전에 질문을 했다. 아래 사정 중에서 질문받은 것에만 짧게 답하라. 묻지 않은 것은 말하지 않는다. 모르는 건 '그건 알아서 해 줘'.
- 보고서는 매주 월요일 9시 발주 회의에서 화면에 띄운다. 협력 운송사 담당자도 함께 본다.
- 지금은 팀장이 엑셀을 직접 훑으며 날짜를 계산해 20분 걸리고 가끔 놓친다(지난달 냉동만두 결품).
- 회의 시작 5분 안에, 다음 입고 전에 재고가 바닥나는 품목을 빠짐없이 알고 발주를 정하고 싶다.
- 매입단가는 회의 자료에 넣으면 안 된다(운송사 담당자도 봄). 화면 한 장 분량이면 좋다.
- 매출 분석 · 그래프 · 유통기한 관리는 필요 없다(별도 회의)."""

CODE = EVID.replace("이번 주 재고 데이터야. 아래 틀에 맞게 정리해 줘.",
    "이번 주 재고 데이터야. 아래 틀에 맞는 보고서를 만들어 줘. 날짜 · 나눗셈 계산은 직접 하지 말고, 보고서를 출력(print)하는 파이썬 코드를 써 줘. 데이터는 변수 DATA(아래 표와 같은 탭 구분 문자열, 첫 줄은 기준일)로 주어진다. 코드 블록 하나만 답해.")
COND = {"A": REQ, "B": REQ + POLISH, "C": FRAME, "D": ASK, "E": EVID, "F": CODE}

RISK_WORDS = ["결품", "소진", "부족", "위험", "긴급", "품절", "바닥", "발주 필요", "재고 없음", "재고 0", "시급", "우선 발주", "추가 발주", "입고 전"]
SAFE_WORDS = ["없음", "안전", "충분", "여유", "정상", "양호", "문제없", "불필요"]
NONGOAL = {"매출": ["매출"], "그래프": ["그래프", "차트"], "유통기한": ["유통기한", "임박"]}


def chat(msgs, temp=0.7):
    for k in range(5):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, temperature=temp)
            return r.choices[0].message.content, r.usage.prompt_tokens + r.usage.completion_tokens
        except Exception as e:
            time.sleep(3 + k * 3)
    raise RuntimeError("API 실패")


HARD = ["결품", "품절", "재고 없음", "재고 0", "바닥", "소진"]
SIZE = re.compile(r"\s*\d+(\.\d+)?\s*(kg|g|L|ml)$")
CORE = {r[0]: SIZE.sub("", r[1]).replace(" ", "") for r in ROWS}


def items_in(line):
    t = line.replace(" ", "")
    return {c for c in CORE if c in line or CORE[c] in t}


def is_risky(line):
    line = line.replace(" ", "")      # '발주필요' · '재고없음' 처럼 띄어쓰기가 달라도
    sp = lambda ws: [w.replace(" ", "") for w in ws]
    if not any(w in line for w in sp(RISK_WORDS)):
        return False
    rest = line.replace("재고없음", "")
    if any(w in rest for w in sp(SAFE_WORDS)) and not any(w in line for w in sp(HARD)):
        return False      # '위험 없음' · '재고 충분'
    if ("유통" in line or "임박" in line) and not any(w in line for w in sp(HARD + ["입고 전"])):
        return False      # 유통기한 주의는 결품 표시가 아님
    return True


def is_head(line):
    s = line.strip().rstrip(":").strip()
    return line.strip().startswith("#") or (s.startswith("**") and s.endswith("**")) or line.strip().endswith(":") \
        or re.match(r"^\d+\.\s*\*\*[^*]+\*\*\s*$", s) is not None


def flagged(report):
    """보고서가 '다음 입고 전 바닥남(결품 위험)'으로 표시한 품목 코드 집합.
    줄 안에 위험 말이 있거나, 위험 말이 든 제목 아래 목록 · 표 줄에 있으면 표시한 것으로 본다."""
    out, sec = set(), False
    for line in report.splitlines():
        its = items_in(line)
        if is_head(line) and not its:
            sec = is_risky(line)
            continue
        if not its:
            continue
        if is_risky(line) or (sec and not any(w in line.replace("재고 없음", "") for w in SAFE_WORDS)):
            out |= its
    return out


def leaked_price(report):
    return sorted({str(r[6]) for r in ROWS if (f"{r[6]:,}" in report or str(r[6]) in report)})


NUM = re.compile(r"-?\d+(?:\.\d+)?")


def evidence_ok(report):
    """위험 품목 6개 중, 같은 줄에 '버티는 날 수'(±0.06)와 '입고까지 남은 날 수'가 정확히 함께 있는 수 — 팀장이 검산할 수 있나."""
    n = 0
    for r in ROWS:
        if r[0] not in RISK:
            continue
        cover, days = r[3] / r[4], arrive_days(r[5])
        for line in report.splitlines():
            if r[0] in line or CORE[r[0]] in line.replace(" ", ""):
                nums = [float(x) for x in NUM.findall(line.replace(",", ""))]
                if any(abs(x - cover) < 0.06 for x in nums) and days in nums:
                    n += 1
                    break
    return n


def nongoal(report):
    out = []
    for k, ws in NONGOAL.items():
        for line in report.splitlines():
            if any(w in line for w in ws) and not any(x in line for x in ["제외", "별도", "비목표", "않", "없", "생략", "빼"]):
                out.append(k)
                break
    return out


def grade(report):
    f = flagged(report)
    return dict(found=sorted(f & RISK), missed=sorted(RISK - f), false=sorted(f - RISK), price=leaked_price(report),
                nongoal=nongoal(report), evidence=evidence_ok(report), chars=len(report))


def run(cond, i):
    t0 = time.time()
    msgs = [{"role": "user", "content": COND[cond]}]
    rep, tok = chat(msgs)
    qa = None
    if cond == "D":
        # 첫 답이 질문이면 팀장이 답하고, 그 뒤에 보고서를 받는다
        if "?" in rep[:1500] and len(rep) < 1500:
            ans, t2 = chat([{"role": "system", "content": MANAGER}, {"role": "user", "content": rep}], temp=0.3)
            msgs += [{"role": "assistant", "content": rep}, {"role": "user", "content": ans + "\n\n이제 보고서 만들어 줘."}]
            qa = dict(q=rep, a=ans)
            rep, t3 = chat(msgs)
            tok += t2 + t3
    code = None
    if cond == "F":
        # 모델이 쓴 계산 코드를 실제로 돌려, 그 출력을 보고서로 쓴다
        # 오류가 나면 오류 메시지를 돌려주고 고치게 한다 (최대 3번 실행 — 사람이 코드를 돌려 보고 고치는 것과 같음)
        import subprocess, tempfile
        msgs += [{"role": "assistant", "content": rep}]
        errors = []
        for attempt in range(3):
            m = re.search(r"```(?:python)?\n(.*?)```", rep, re.S)
            code = m.group(1) if m else rep
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, "report.py")
                open(f, "w", encoding="utf-8").write("DATA = " + repr(TABLE) + "\n" + code)
                try:
                    pr = subprocess.run([sys.executable, "-I", "-X", "utf8", f], capture_output=True, text=True, encoding="utf-8",
                                        errors="replace", timeout=30, cwd=d, env={"PYTHONIOENCODING": "utf-8", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})
                    ok, out = pr.returncode == 0, (pr.stdout if pr.returncode == 0 else pr.stderr[-800:])
                except subprocess.TimeoutExpired:
                    ok, out = False, "실행 시간 초과"
            if ok:
                rep = out
                break
            errors.append(out)
            msgs.append({"role": "user", "content": "실행했더니 오류가 났어. 고친 코드 블록 하나만 다시 줘.\n" + out})
            rep, t4 = chat(msgs)
            tok += t4
            msgs.append({"role": "assistant", "content": rep})
        else:
            rep = "실행 오류 3번"
        qa = dict(errors=errors)
    g = grade(rep)
    return dict(cond=cond, i=i, report=rep, code=code, qa=qa, tokens=tok, sec=round(time.time() - t0, 1), **g)


if __name__ == "__main__":
    print("정답 위험 품목:", sorted(RISK))
    conds = sys.argv[1:] or list(COND)
    jobs = [(c, i) for c in conds for i in range(TRIALS)]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda a: run(*a), jobs))
    out = os.path.join(HERE, "results.json")
    old = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    old = [r for r in old if r["cond"] not in conds] + res
    json.dump(old, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for c in conds:
        rs = [r for r in res if r["cond"] == c]
        ok = sum(1 for r in rs if not r["missed"] and not r["false"] and not r["price"])
        print(c, "완벽", ok, "/", len(rs), "| 찾음 평균 %.1f/6" % (sum(len(r["found"]) for r in rs) / len(rs)),
              "| 잘못표시 합", sum(len(r["false"]) for r in rs), "| 단가노출", sum(1 for r in rs if r["price"]),
              "| 비목표", sum(1 for r in rs if r["nongoal"]), "| 글자 %d" % (sum(r["chars"] for r in rs) / len(rs)),
              "| 질문함", sum(1 for r in rs if r["qa"]), "| 검산가능 평균 %.1f/6" % (sum(r["evidence"] for r in rs) / len(rs)),
              "| 토큰 %d" % (sum(r["tokens"] for r in rs) / len(rs)))
