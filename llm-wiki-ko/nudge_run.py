# -*- coding: utf-8 -*-
"""5편 v3 보조 실험: ep5b 에서 저장 없이 끝난 개정 원본(생성형 AI 보완 공지)을 같은 상태의 위키 복사본에 여러 번 넣어
'보고문에만 쓰고 끝내기' 가 몇 번 생기는지, --require-write 재촉이 그중 몇 번을 살리는지 잰다.
사용: python _scratch/wiki/nudge_run.py [--trials=5] [--base=wiki_ep5b] [--src=policies/개정공지_2026-10-15_생성형AI.md] [--page=규정/18-보안-생성형-AI-사용] [--must=구매팀장]
결과 results/nudge_trial.json — 조건(off/on) × 시도: 저장 여부 · 재촉 여부 · 페이지에 새 값이 들어갔나 · 토큰."""
import json, os, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
opt = lambda k, d=None: next((a.split("=", 1)[1] for a in args if a.startswith("--%s=" % k)), d)
TRIALS = int(opt("trials", 5))
BASE = os.path.join(HERE, opt("base", "wiki_ep5b"))
SRC = os.path.join(E.RAW, opt("src", "policies/개정공지_2026-10-15_생성형AI.md"))
PAGE = opt("page", "규정/18-보안-생성형-AI-사용")
MUST = opt("must", "구매팀장")
TODAY = json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))["today"]
SCHEMA = os.path.join(HERE, "schema_ep5.md")
CONDS = [c == "on" for c in opt("conds", "off,on").split(",")]     # --conds=on 이면 재촉 ON 만
OUTFILE = opt("out", "nudge_trial.json")
out = []
for require in CONDS:
    for t in range(TRIALS):
        tmp = tempfile.mkdtemp(prefix="nudge_", dir=HERE)
        shutil.rmtree(tmp); shutil.copytree(BASE, tmp, ignore=shutil.ignore_patterns("BUILT"))
        w = E.Wiki(tmp, schema_path=SCHEMA)
        before = w.read_page(PAGE) or ""
        t0 = time.time()
        r = E.ingest(w, SRC, TODAY, tally=True, auto_index=True, amend_guard=True, require_write=require)
        after = w.read_page(PAGE) or ""
        rec = dict(require_write=require, trial=t, wrote=bool(r["pages_written"]), nudged=r.get("nudged", False),
                   merged=(MUST in after and MUST not in before), pages_written=r["pages_written"], steps=r["steps"], tokens=r["tokens"], sec=round(time.time() - t0))
        out.append(rec)
        print("%s t%d  저장=%s 재촉=%s 합쳐짐=%s steps=%d tok=%d" % ("재촉 ON " if require else "재촉 OFF", t, rec["wrote"], rec["nudged"], rec["merged"], rec["steps"], rec["tokens"]), flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
json.dump(dict(base=os.path.basename(BASE), src=os.path.relpath(SRC, E.RAW).replace("\\", "/"), page=PAGE, must=MUST, trials=TRIALS, runs=out),
          open(os.path.join(HERE, "results", OUTFILE), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for require in CONDS:
    rs = [r for r in out if r["require_write"] == require]
    print("== 재촉 %s: %d회 중 저장 없이 끝남 %d · 재촉 발동 %d · 새 값 합쳐짐 %d" % ("ON" if require else "OFF", len(rs), sum(not r["wrote"] for r in rs), sum(r["nudged"] for r in rs), sum(r["merged"] for r in rs)))
