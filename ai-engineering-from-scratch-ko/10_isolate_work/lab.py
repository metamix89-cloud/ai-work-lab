# -*- coding: utf-8 -*-
"""ep056 실습 — 시즌 2 10편: 나눠 맡길 때는 칸을 나눠라 (원본 Phase 14 레슨 45 'Delegate Agent Work with Isolation and Merge Contracts').
가나다식품(가상) 상품 안내 문서를 에이전트 3명(가격 · 알레르기 · 배송 담당)이 동시에 고친다. gpt-4.1-mini, 조건마다 10회.
  A 한 파일 같이     : 3명이 같은 파일(상품안내.md)을 동시에 읽고 · 고치고 · 통째로 저장
  C 말로만 담당      : A + "네 담당은 ○○ 칸뿐, 다른 칸은 고치지 마라" (파일은 여전히 하나)
  B 파일을 나눔      : 칸마다 파일 하나, 담당 파일에만 쓸 수 있음(다른 파일 쓰기는 도구가 거부) → 코드가 순서대로 이어 붙임
  S 차례로           : 같은 파일을 한 명씩 차례로
채점(코드): 최종 문서에 세 사람의 수정 7개가 살아 있나 · 다른 사람 칸을 고치려 한 횟수 · 걸린 시간.
병렬 실험 주의(lab-thread-cache 교훈): 가짜 파일 시스템은 실행마다 새로 만들고, 실행 안의 스레드끼리만 공유한다."""
import copy, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv()
client = OpenAI()
MODEL = "gpt-4.1-mini"
TRIALS = int(os.environ.get("TRIALS", 10))

SEC = {
    "price": """## 1. 가격표 (박스 기준, 부가세 포함)
- 떡볶이 소스 2kg: 73,400원
- 고추장 500g: 46,200원
- 된장 1kg: 39,800원""",
    "allergy": """## 2. 알레르기 표시
- 떡볶이 소스 2kg: 대두, 밀
- 견과 선물세트: 땅콩
- 김자반 50g: 대두""",
    "ship": """## 3. 배송 · 반품 안내
- 당일 출고 마감: 오후 3시 주문까지
- 냉동식품 반품: 수령 후 7일 이내
- 3만 원 이상 무료배송""",
}
HEAD = "# 가나다식품 거래처용 상품 안내 (2026년 11월판)"
DOC = HEAD + "\n\n" + "\n\n".join(SEC[k] for k in ("price", "allergy", "ship")) + "\n"

TASK = {
    "price": "가격표를 고쳐라: 떡볶이 소스 2kg 79,270원, 고추장 500g 47,500원으로. 된장은 그대로.",
    "allergy": "알레르기 표시를 고쳐라: 견과 선물세트에 '호두, 아몬드'를 추가하고, 김자반 50g에 '참깨'를 추가.",
    "ship": "배송 · 반품 안내를 고쳐라: 당일 출고 마감을 오후 2시로, 냉동식품 반품을 수령 후 14일 이내로.",
}
NAME = {"price": "가격 담당", "allergy": "알레르기 담당", "ship": "배송 담당"}
SECTION_NAME = {"price": "1. 가격표", "allergy": "2. 알레르기 표시", "ship": "3. 배송 · 반품 안내"}
FILES_B = {"price": "상품안내/1_가격표.md", "allergy": "상품안내/2_알레르기.md", "ship": "상품안내/3_배송.md"}

TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "파일 읽기", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "파일 전체를 새 내용으로 저장", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
]


def worker(role, cond, fs, lock, log):
    if cond == "B":
        sysmsg = "너는 %s 에이전트다. 네 담당 파일은 %s 하나다. 다른 파일에는 쓸 수 없다." % (NAME[role], FILES_B[role])
        user = TASK[role] + "\n파일: " + FILES_B[role]
    else:
        sysmsg = "너는 %s 에이전트다. 공유 문서 상품안내.md 를 고친다." % NAME[role]
        user = TASK[role] + "\n파일: 상품안내.md"
        if cond == "C":
            user += "\n네 담당은 '%s' 칸뿐이다. 다른 칸은 고치지 마라." % SECTION_NAME[role]
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]
    for _ in range(8):
        for k in range(5):
            try:
                r = client.chat.completions.create(model=MODEL, messages=msgs, tools=TOOLS, temperature=0.7)
                break
            except Exception:
                time.sleep(3 + 3 * k)
        m = r.choices[0].message
        msgs.append(m.model_dump(exclude_none=True))
        if not m.tool_calls:
            break
        for tc in m.tool_calls:
            a = json.loads(tc.function.arguments or "{}")
            p = (a.get("path") or "").strip().lstrip("./")
            with lock:   # 도구 한 번은 원자적 — 그래도 '읽고 → 한참 뒤 통째로 쓰기'는 끼어들 수 있다
                if tc.function.name == "read_file":
                    out = {"content": fs[p]} if p in fs else {"error": "없는 파일"}
                    log.append((time.time(), role, "read", p))
                else:
                    if cond == "B" and p != FILES_B[role]:
                        out = {"error": "거부: 담당 파일이 아님 (%s 만 쓸 수 있음)" % FILES_B[role]}
                        log.append((time.time(), role, "denied", p))
                    else:
                        fs[p] = a.get("content", "")
                        out = {"ok": True}
                        log.append((time.time(), role, "write", p))
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out, ensure_ascii=False)})


def run(cond, i):
    lock, log = threading.Lock(), []
    if cond == "B":
        fs = {FILES_B[k]: SEC[k] + "\n" for k in SEC}
    else:
        fs = {"상품안내.md": DOC}
    t0 = time.time()
    if cond == "S":
        for role in ("price", "allergy", "ship"):
            worker(role, cond, fs, lock, log)
    else:
        th = [threading.Thread(target=worker, args=(role, cond, fs, lock, log)) for role in ("price", "allergy", "ship")]
        for t in th:
            t.start()
        for t in th:
            t.join()
    sec = time.time() - t0
    final = (HEAD + "\n\n" + "\n".join(fs[FILES_B[k]].strip() + "\n" for k in ("price", "allergy", "ship"))) if cond == "B" else fs["상품안내.md"]
    g = grade(final)
    writes = [(r, p) for _, r, op, p in log if op == "write"]
    return dict(cond=cond, i=i, final=final, sec=round(sec, 1), log=[(round(t - t0, 1), r, op, p) for t, r, op, p in log],
                n_writes=len(writes), denied=sum(1 for _, _, op, _ in log if op == "denied"), **g)


CHECKS = [
    ("가격: 떡볶이 79,270", r"떡볶이 소스 2kg[^\n]*79,?270"),
    ("가격: 고추장 47,500", r"고추장 500g[^\n]*47,?500"),
    ("알레르기: 견과 호두", r"견과 선물세트[^\n]*호두"),
    ("알레르기: 견과 아몬드", r"견과 선물세트[^\n]*아몬드"),
    ("알레르기: 김자반 참깨", r"김자반[^\n]*참깨"),
    ("배송: 마감 2시", r"마감[^\n]*(오후 ?2시|14시|14:00)"),
    ("배송: 반품 14일", r"반품[^\n]*14일"),
]
KEEP = [r"된장 1kg[^\n]*39,?800", r"떡볶이 소스 2kg: [^\n]*대두", r"3만 원 이상 무료배송"]


def grade(final):
    got = [name for name, pat in CHECKS if re.search(pat, final)]
    kept = sum(1 for pat in KEEP if re.search(pat, final))
    return dict(survived=got, n_survived=len(got), kept=kept, ok=len(got) == len(CHECKS) and kept == len(KEEP))


def summary(rs):
    for c in ["A", "C", "B", "S"]:
        x = [r for r in rs if r["cond"] == c]
        if not x:
            continue
        print(c, "완벽 %d/%d" % (sum(r["ok"] for r in x), len(x)), "| 살아남은 수정 평균 %.1f/7" % (sum(r["n_survived"] for r in x) / len(x)),
              "| 그대로 둘 것 유지 %.1f/3" % (sum(r["kept"] for r in x) / len(x)), "| 쓰기 거부 %d" % sum(r["denied"] for r in x),
              "| 시간 %.1f초" % (sum(r["sec"] for r in x) / len(x)))


if __name__ == "__main__":
    conds = sys.argv[1:] or ["A", "C", "B", "S"]
    jobs = [(c, i) for c in conds for i in range(TRIALS)]
    with ThreadPoolExecutor(4) as ex:      # 실행끼리는 4개씩, 실행 안에서 에이전트 3명이 각자 스레드
        res = list(ex.map(lambda a: run(*a), jobs))
    out = os.path.join(HERE, "results.json")
    old = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else []
    old = [r for r in old if r["cond"] not in conds] + res
    json.dump(old, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summary(old)
