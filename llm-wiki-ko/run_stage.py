# -*- coding: utf-8 -*-
"""편별 실험(2~5 · 7편): 원본 묶음을 골라 위키를 만들고(또는 앞 편 위키 위에 더 넣고), 같은 묶음만 보는 RAG · 원본 통째와 비교한다.
사용: python run_stage.py --name=ep2 --groups=cs --qgroups=Q1 [--base=wiki_ep2_in] [--schema=schema.md] [--conds=rag,wiki,dump] [--trials=3] [--only=Q1-01,Q1-02]
  --groups  : 이번에 넣을 raw/ 하위 폴더(쉼표). 위키는 wiki_<name>/ 에 만든다(--base 가 있으면 그 폴더를 복사한 뒤 더 넣는다)
  --qgroups : 물을 질문 그룹(쉼표). RAG · dump 는 base 의 묶음 + 이번 묶음 파일을 본다(--all-raw 면 57개 전부)
  --schema  : 위키 규칙 파일(편마다 규칙을 하나씩 더한 schema_ep3.md 같은 것)
결과 results/<name>.json (run_ep1 과 같은 형식, summarize.py · regrade.py 가 읽음) + results/build_<name>.json"""
import glob, json, os, shutil, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
from grade import grade_answer, grounded

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
opt = lambda k, d=None: next((a.split("=", 1)[1] for a in args if a.startswith("--%s=" % k)), d)
NAME = opt("name", "stage")
GROUPS = opt("groups", "").split(",") if opt("groups") else []
QGROUPS = set(opt("qgroups", "Q1,Q2,Q3,Q4,Q5").split(","))
BASE = opt("base")
SCHEMA = os.path.join(HERE, opt("schema", "schema.md"))
CONDS = opt("conds", "rag,wiki").split(",")
TRIALS = int(opt("trials", 3))
ONLY = set(opt("only").split(",")) if opt("only") else None
ALL_RAW = "--all-raw" in args
TALLY = "--tally" in args            # 넣기 때 표 건수를 코드 도구(tally_table)로 세게 한다 (2편 v3)
AUTO_INDEX = "--auto-index" in args  # 목차를 코드가 페이지에서 다시 만든다 (2편 v4) — 모델의 write_index 는 막는다
GRADE_ORDER = "--grade-order" in args  # 3편 v2: 묶음 안에서 등급 높은 원본(계약 · 단가표)부터 넣는다
GRADE_GUARD = "--grade-guard" in args  # 3편 v2: 등급 4 · 5 원본은 새 페이지를 못 만들고, 품목 이름은 코드가 정식 이름으로 맞춘다
QFILE = json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))
TODAY = QFILE["today"]
QS = [q for q in QFILE["questions"] if q["group"] in QGROUPS and (ONLY is None or q["id"] in ONLY)]
OUT = os.path.join(HERE, "results"); os.makedirs(OUT, exist_ok=True)
WDIR = os.path.join(HERE, "wiki_" + NAME)


def group_files(groups):
    fs = []
    for g in groups:
        fs += sorted(glob.glob(os.path.join(E.RAW, g, "*.*")))
    return fs


def build():
    """wiki_<name>/ 을 만든다: base 복사 → 이번 묶음 ingest. 이미 BUILT 표시가 있으면 건너뛴다."""
    if os.path.exists(os.path.join(WDIR, "BUILT")):
        return
    shutil.rmtree(WDIR, ignore_errors=True)
    if BASE:
        shutil.copytree(os.path.join(HERE, BASE), WDIR, ignore=shutil.ignore_patterns("BUILT"))
    w = E.Wiki(WDIR, schema_path=SCHEMA)
    log, t0 = [], time.time()
    files = group_files(GROUPS)
    if GRADE_ORDER:
        files = sorted(files, key=lambda f: (E.grade_of(f), f))
    for i, f in enumerate(files, 1):
        r = E.ingest(w, f, TODAY, tally=TALLY, auto_index=AUTO_INDEX, grade_guard=GRADE_GUARD); r["stats"] = w.stats(); log.append(r)
        r["grade"] = E.grade_of(f)
        print("[%2d/%d] %-45s pages=%-3d tok=%d" % (i, len(files), r["source"][:45], r["stats"]["pages"], r["tokens"]), flush=True)
    json.dump(dict(name=NAME, base=BASE, groups=GROUPS, schema=os.path.basename(SCHEMA), sec=round(time.time() - t0), log=log, stats=w.stats()),
              open(os.path.join(OUT, "build_%s.json" % NAME), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(WDIR, "BUILT"), "w").write(TODAY)


def seen_groups():
    """RAG · dump 가 볼 파일: base 가 본 묶음 + 이번 묶음 (build_<base>.json 의 groups 를 거슬러 모음)."""
    if ALL_RAW:
        return E.raw_files()
    gs, b = list(GROUPS), BASE
    while b:
        bj = os.path.join(OUT, "build_%s.json" % b.replace("wiki_", ""))
        if not os.path.exists(bj):
            break
        d = json.load(open(bj, encoding="utf-8")); gs = d["groups"] + gs; b = d.get("base")
    return group_files(gs)


def run(cond):
    files = seen_groups()
    if cond == "dump":
        fn, trials = (lambda q: E.baseline_dump(q["q"], TODAY, files)), TRIALS
    elif cond == "rag":
        rag = E.RAG(files); fn, trials = (lambda q: rag.answer(q["q"], TODAY)), TRIALS
    else:
        build(); w = E.Wiki(WDIR, schema_path=SCHEMA); fn, trials = (lambda q: E.query(w, q["q"], TODAY)), TRIALS
    jobs = [(q, t) for q in QS for t in range(trials)]

    def one(job):
        q, t = job
        try:
            r = fn(q)
        except Exception as e:
            return dict(cond=cond, id=q["id"], trial=t, error=str(e)[:200])
        ok, why = grade_answer(q, r["answer"])
        return dict(cond=cond, id=q["id"], group=q["group"], kind=q["kind"], trial=t, ok=ok, why=why, grounded=grounded(q, r["answer"]),
                    answer=r["answer"][:1500], tokens=r["tokens"], pages=r.get("pages_read") or r.get("chunks"))
    with ThreadPoolExecutor(4 if cond == "dump" else 6) as ex:
        return list(ex.map(one, jobs))


if __name__ == "__main__":
    path = os.path.join(OUT, NAME + ".json")
    res = [r for r in json.load(open(path, encoding="utf-8"))] if os.path.exists(path) else []
    res = [r for r in res if r["cond"] not in CONDS or (ONLY and r.get("id") not in ONLY)]
    for c in CONDS:
        t0 = time.time(); rr = run(c); res += rr
        print("== %s: %d/%d 정답, 근거 %d, 토큰 평균 %.0f, %.0fs" % (c, sum(1 for r in rr if r.get("ok")), len(rr), sum(1 for r in rr if r.get("grounded")),
                                                             sum(r.get("tokens", 0) for r in rr) / max(1, len(rr)), time.time() - t0), flush=True)
        json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
