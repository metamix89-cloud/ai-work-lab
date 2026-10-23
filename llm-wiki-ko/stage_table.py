# -*- coding: utf-8 -*-
"""한 편의 여러 단계(results/<name>.json 여러 개)를 한 표로: 조건별 정답 · 근거 · 토큰, 페이지 수 · 고아 · 빌드 토큰.
사용: python _scratch/wiki/stage_table.py ep2:rag ep2:wiki ep2r:wiki ep2b:wiki ep2c:wiki ep2d:wiki --only=Q1-01,Q1-03,...
  항목은 <결과파일>:<조건>. --only 로 문항을 제한. 위키 폴더는 wiki_<결과파일> 에서 찾는다(없으면 - )."""
import glob, json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
ids = next((set(a.split("=", 1)[1].split(",")) for a in args if a.startswith("--only=")), None)
items = [a for a in args if not a.startswith("--")]
print("%-12s %7s %7s %9s %6s %5s %10s" % ("단계", "정답", "근거", "토큰/문항", "페이지", "고아", "빌드 토큰"))
for it in items:
    name, cond = it.split(":")
    res = [r for r in json.load(open(os.path.join(HERE, "results", name + ".json"), encoding="utf-8"))
           if "ok" in r and r["cond"] == cond and (ids is None or r["id"] in ids)]
    n = len(res)
    wdir = os.path.join(HERE, "wiki_" + name) if cond == "wiki" else None
    pages, orphans, btok = "-", "-", "-"
    if wdir and os.path.exists(wdir):
        slugs = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(wdir, "pages", "*.md"))]
        idx = open(os.path.join(wdir, "index.md"), encoding="utf-8").read()
        pages = len(slugs); orphans = sum(1 for s in slugs if s not in idx and s.replace("-", "/", 1) not in idx)
        bj = os.path.join(HERE, "results", "build_%s.json" % ("full" if name == "ep1" else name))
        if os.path.exists(bj):
            btok = format(sum(r["tokens"] for r in json.load(open(bj, encoding="utf-8"))["log"]), ",")
    print("%-12s %3d/%-3d %3d/%-3d %9.0f %6s %5s %10s" % (it, sum(r["ok"] for r in res), n, sum(1 for r in res if r["grounded"]), n,
                                                        sum(r["tokens"] for r in res) / max(1, n), pages, orphans, btok))
