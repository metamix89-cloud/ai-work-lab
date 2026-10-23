# -*- coding: utf-8 -*-
"""6편 실험: 위키 한 벌에 engine.lint(위키 전체를 한 번에 읽는 점검)를 N번 돌려 심은 모순(lint_items.json)을 몇 개 찾는지 잰다.
사용: python _scratch/wiki/lint_run.py --wiki=wiki_full [--trials=3] [--groups=cs,suppliers,...] [--name=lint_full] [--mode=whole|sections]
  --groups : 그 위키에 든 raw 묶음(없으면 build_<name>.json 을 거슬러 모음, 못 찾으면 전부)
  --mode   : whole = 전문 한 번에(기본, engine.lint) · sections = 코드가 대상(상품 · 거래처 · 규정 주제)별 페이지 묶음을 만들어 묶음마다 묻고 합침(6편 v2)
             · verify = sections + 상충 후보를 한 건씩 해당 페이지와 다시 물어 '상충' 만 남김(6편 v3, 오탐 · 중복 제거)
결과 results/<name>.json — 돌린 횟수마다 raw lint 결과 · 토큰 · 채점(lint_grade.grade_lint)"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
from lint_grade import grade_lint
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
opt = lambda k, d=None: next((a.split("=", 1)[1] for a in args if a.startswith("--%s=" % k)), d)
WIKI = opt("wiki", "wiki_full")
TRIALS = int(opt("trials", 3))
NAME = opt("name", "lint_" + WIKI.replace("wiki_", ""))
MODE = opt("mode", "whole")
TODAY = json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))["today"]
WDIR = os.path.join(HERE, WIKI)


def groups_of(wiki):
    if opt("groups"):
        return opt("groups").split(",")
    gs, b = [], wiki.replace("wiki_", "")
    while b:
        bj = os.path.join(HERE, "results", "build_%s.json" % b)
        if not os.path.exists(bj):
            return None if not gs else gs
        d = json.load(open(bj, encoding="utf-8")); gs = d.get("groups", []) + gs; b = (d.get("base") or "").replace("wiki_", "")
    return gs or None


w = E.Wiki(WDIR)
groups = groups_of(WIKI)
text = w.all_text()
runs = []
for t in range(TRIALS):
    t0 = time.time()
    r = E.lint(w, TODAY) if MODE == "whole" else E.lint_sections(w, TODAY) if MODE == "sections" else E.lint_sections_verified(w, TODAY)
    g = grade_lint(r["result"], text, groups=groups, wdir=WDIR)
    runs.append(dict(trial=t, mode=MODE, tokens=r["tokens"], sec=round(time.time() - t0), result=r["result"], grade=g))
    print("t%d  범위 %d · 두 값 다 있음 %d · 찾음 %d(그중 %d) · 판단 맞음 %d · 보고 %d · 미매칭 %d · 고아 %s · 토큰 %d · %ds" % (
        t, g["n"], g["both"], g["found"], g["found_of_both"], g["judged"], g["reported"], len(g["unmatched"]), g.get("orphans"), r["tokens"], runs[-1]["sec"]), flush=True)
json.dump(dict(wiki=WIKI, mode=MODE, groups=groups, today=TODAY, runs=runs), open(os.path.join(HERE, "results", NAME + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장: results/%s.json" % NAME)
