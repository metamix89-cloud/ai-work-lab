# -*- coding: utf-8 -*-
"""8편 실험: '11월 기획 보고서 — 무엇을 밀고 무엇을 줄일까' 를 조건마다 N번 쓰게 하고 코드로 채점한다(report_grade).
조건: wiki(위키 에이전트, 읽기 도구 · 최대 12장) · rag(검색 상위 12개 청크) · dump(원본 통째). 모두 같은 원본 57개(ops 제외).
사용: python _scratch/wiki/report_run.py [--wiki=wiki_ep7] [--conds=wiki,rag,dump] [--trials=10] [--name=ep8]
결과 results/<name>.json — 조건 × 회차별 보고서 전문 · 토큰 · 채점"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
from report_grade import grade_report
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
opt = lambda k, d=None: next((a.split("=", 1)[1] for a in args if a.startswith("--%s=" % k)), d)
WIKI = opt("wiki", "wiki_ep7"); CONDS = opt("conds", "wiki,rag,dump").split(","); TRIALS = int(opt("trials", 10)); NAME = opt("name", "ep8")
MODE = opt("mode", "direct")      # direct = 보고서를 한 번에 쓰게 함 · split = 코드가 질문 5개로 쪼개 하나씩 묻고(묻기 에이전트) 답을 모아 쓰게 함 (8편 v2)
SUBQ = ["최근 3개월 연속 매출이 늘고 있는 상품은 무엇이고 월별 수치는?",
        "재고가 과다한 상품(버티는 날 기준)은 무엇이고 재고 수량과 입고 권고는?",
        "11월에 확정된 판촉은 무엇이고 어떤 상품 · 할인 조건인가?",
        "품질 문제(변질 · 리뷰)로 11월 판촉에서 빼야 할 상품은 무엇이고 이유는?",
        "고객 리뷰 평점이 낮은 상품은 무엇이고 어떤 불만인가? 노출 제한 대상은?"]
COMPOSE = ("아래는 회사 자료에 하나씩 물어 얻은 답이다. 이 답에 있는 사실과 숫자만 써서 보고서를 쓴다. 답에 없는 숫자는 쓰지 않는다.\n\n[조사 결과]\n%s\n\n[보고서 요청]\n%s")
TODAY = json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))["today"]
TASK = ("11월 기획 보고서를 써라. 제목: '11월 무엇을 밀고 무엇을 줄일까'. 매출 추이 · 재고 · 고객 반응(리뷰) · 확정된 판촉 · 품질 이슈를 근거로 "
        "(1) 밀 것 (2) 줄이거나 취소할 것 (3) 판촉에서 빼야 할 것 (4) 손볼 것 을 각각 한두 줄로, 줄마다 숫자 근거와 출처(페이지 · 파일)를 붙여라. 10줄 이내. "
        "자료에 없는 숫자는 쓰지 말고, 모르면 '자료 없음' 이라고 쓴다.")
files = [f for f in E.raw_files() if "/ops/" not in f.replace("\\", "/")]


def ask(cond, w, rag, q, limit=12):
    if cond == "wiki":
        return E.query(w, q, TODAY, search=True, read_limit=limit)
    if cond == "rag":
        return rag.answer(q, TODAY)
    return E.baseline_dump(q, TODAY, files)


def one(cond, w, rag, t):
    t0 = time.time()
    try:
        if MODE == "direct":
            r = ask(cond, w, rag, TASK)
        else:                                                     # split: 질문 5개 → 답 모음 → 작성
            answers, tok = [], 0
            for q in SUBQ:
                a = ask(cond, w, rag, q, limit=8); tok += a["tokens"]; answers.append("Q: %s\nA: %s" % (q, a["answer"]))
            m, t2 = E.chat([{"role": "system", "content": E.BASE_SYS.format(today=TODAY)}, {"role": "user", "content": COMPOSE % ("\n\n".join(answers), TASK)}])
            r = dict(answer=m.content or "", tokens=tok + t2, sub_answers=answers)
    except Exception as e:
        return dict(cond=cond, trial=t, error=str(e)[:200])
    g = grade_report(r["answer"])
    return dict(cond=cond, trial=t, mode=MODE, report=r["answer"], tokens=r["tokens"], sec=round(time.time() - t0), grade=g, sub_answers=r.get("sub_answers"))


out = []
for cond in CONDS:
    w = E.Wiki(os.path.join(HERE, WIKI), schema_path=os.path.join(HERE, "schema_ep5.md")) if cond == "wiki" else None
    rag = E.RAG(files, topk=12) if cond == "rag" else None
    with ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda t: one(cond, w, rag, t), range(TRIALS)))
    out += rs
    ok = [r for r in rs if "grade" in r]
    print("== %s: 요소 평균 %.1f/5 · 근거 %.1f · 지어낸 숫자 합 %d · 심은 틀린 값 %d · 토큰 평균 %.0f" % (
        cond, sum(r["grade"]["found"] for r in ok) / max(1, len(ok)), sum(r["grade"]["grounded"] for r in ok) / max(1, len(ok)),
        sum(len(r["grade"]["made_up"]) for r in ok), sum(len(r["grade"]["planted_wrong"]) for r in ok), sum(r["tokens"] for r in ok) / max(1, len(ok))), flush=True)
    json.dump(out, open(os.path.join(HERE, "results", NAME + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
