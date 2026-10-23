# -*- coding: utf-8 -*-
"""1편 실험: 같은 50문항을 ① 원본 통째(dump) ② 일반 RAG ③ 빈 위키 ④ 전체 위키(57개 원본을 모두 ingest 한 뒤) 로 답하게 한다.
dump · RAG · full 은 문항당 TRIALS 회, empty 는 1회(답이 '없음' 뿐). 결과 results/ep1.json, 위키 스냅샷 wiki_full/.
사용: python run_ep1.py [--cond=dump,rag,empty,full] [--trials=3] [--build-only]"""
import glob, json, os, shutil, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
from grade import grade_answer, grounded

HERE = os.path.dirname(os.path.abspath(__file__))
QFILE = json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))
TODAY, QS = QFILE["today"], QFILE["questions"]
OUT = os.path.join(HERE, "results"); os.makedirs(OUT, exist_ok=True)
args = sys.argv[1:]
conds = next((a.split("=", 1)[1].split(",") for a in args if a.startswith("--cond=")), ["dump", "rag", "empty", "full"])
TRIALS = int(next((a.split("=", 1)[1] for a in args if a.startswith("--trials=")), 3))
ONLY = next((set(a.split("=", 1)[1].split(",")) for a in args if a.startswith("--only=")), None)   # 특정 문항만 다시 (문구 수정 뒤)
if ONLY:
    QS = [q for q in QS if q["id"] in ONLY]
FILES = E.raw_files()                                       # ops/ 제외 57개
ORDER = ["policies", "suppliers", "customers", "meetings", "sales", "cs"]   # 넣는 순서: 규정 → 거래처 → 회의 → 지표 → 문의


def build_full():
    wdir = os.path.join(HERE, "wiki_full")
    if os.path.exists(os.path.join(wdir, "BUILT")):
        return wdir
    shutil.rmtree(wdir, ignore_errors=True)
    w = E.Wiki(wdir)
    log = []
    files = sorted(FILES, key=lambda f: (ORDER.index(os.path.relpath(f, E.RAW).replace("\\", "/").split("/")[0]), f))
    t0 = time.time()
    for i, f in enumerate(files, 1):
        r = E.ingest(w, f, TODAY)
        r["stats"] = w.stats()
        log.append(r)
        print("[%2d/%d] %-45s pages=%-3d +%s tok=%d" % (i, len(files), r["source"][:45], r["stats"]["pages"], ",".join(r["pages_written"])[:60], r["tokens"]), flush=True)
    json.dump(dict(sec=round(time.time() - t0), log=log, stats=w.stats()), open(os.path.join(OUT, "build_full.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(wdir, "BUILT"), "w").write(TODAY)
    return wdir


def run_cond(cond):
    if cond == "dump":
        fn = lambda q: E.baseline_dump(q["q"], TODAY, FILES)
        trials = TRIALS
    elif cond == "rag":
        rag = E.RAG(FILES)
        fn = lambda q: rag.answer(q["q"], TODAY)
        trials = TRIALS
    elif cond == "empty":
        wdir = os.path.join(HERE, "wiki_empty"); shutil.rmtree(wdir, ignore_errors=True)
        w = E.Wiki(wdir)
        fn = lambda q: E.query(w, q["q"], TODAY)
        trials = 1
    else:
        w = E.Wiki(build_full())
        fn = lambda q: E.query(w, q["q"], TODAY)
        trials = TRIALS
    jobs = [(q, t) for q in QS for t in range(trials)]

    def one(job):
        q, t = job
        try:
            r = fn(q)
        except Exception as e:
            return dict(cond=cond, id=q["id"], trial=t, error=str(e)[:200])
        ok, why = grade_answer(q, r["answer"])
        return dict(cond=cond, id=q["id"], group=q["group"], kind=q["kind"], trial=t, ok=ok, why=why,
                    grounded=grounded(q, r["answer"]), answer=r["answer"][:1500], tokens=r["tokens"],
                    pages=r.get("pages_read") or r.get("chunks"))
    with ThreadPoolExecutor(4 if cond == "dump" else 6) as ex:
        res = list(ex.map(one, jobs))
    return res


if __name__ == "__main__":
    if "--build-only" in args:
        build_full(); sys.exit()
    all_res = []
    path = os.path.join(OUT, "ep1.json")
    if os.path.exists(path):
        old = json.load(open(path, encoding="utf-8"))
        all_res = [r for r in old if r["cond"] not in conds or (ONLY and r.get("id") not in ONLY)]
    for c in conds:
        t0 = time.time()
        res = run_cond(c)
        all_res += res
        ok = [r for r in res if r.get("ok")]
        print("== %s: %d/%d 정답, 근거 %d, 토큰 평균 %.0f, %.0fs" % (c, len(ok), len(res), sum(1 for r in res if r.get("grounded")), sum(r.get("tokens", 0) for r in res) / max(1, len(res)), time.time() - t0), flush=True)
        json.dump(all_res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 그룹별 요약
    from collections import defaultdict
    summ = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in all_res:
        if "ok" in r:
            summ[r["cond"]][r["group"]][0] += r["ok"]; summ[r["cond"]][r["group"]][1] += 1
    for c in summ:
        print(c, " ".join("%s %d/%d" % (g, v[0], v[1]) for g, v in sorted(summ[c].items())))
