# -*- coding: utf-8 -*-
"""9편 실험: 사람이 한 번 고친 사실을 다시 틀리게 적은 새 메모 10건(memos_ep9.json)을 위키에 넣으면 틀린 값이 재발하는가.
조건: plain = 1편 위키(wiki_full) + 1편 규칙(schema.md), 도구 없음 · rules = 규칙 위키(wiki_ep7) + 2~5편 규칙 · 도구
      fixrules = rules + 교정 규칙 10줄(memos_ep9.json 의 rule → schema_ep9.md)
사용: python _scratch/wiki/fix_run.py [--conds=plain,rules,fixrules] [--name=ep9]
결과 results/<name>.json — 조건별: 넣기 전 이미 있던 틀린 값 · 넣은 뒤 재발 페이지 · 토큰"""
import json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
from fix_grade import MEMOS, recurred, wiki_pages
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
opt = lambda k, d=None: next((a.split("=", 1)[1] for a in args if a.startswith("--%s=" % k)), d)
CONDS = opt("conds", "plain,rules,fixrules").split(","); NAME = opt("name", "ep9")
TODAY = "2026-10-30"
BASE = dict(plain=("wiki_full", "schema.md", {}), rules=("wiki_ep7", "schema_ep5.md", dict(tally=True, auto_index=True, amend_guard=True, require_write=True)),
            fixrules=("wiki_ep7", "schema_ep9.md", dict(tally=True, auto_index=True, amend_guard=True, require_write=True)),
            guard=("wiki_ep7", "schema_ep5.md", dict(tally=True, auto_index=True, amend_guard=True, require_write=True, conflict_guard=True)),        # 9편 v2: 코드 가드만
            fixguard=("wiki_ep7", "schema_ep9.md", dict(tally=True, auto_index=True, amend_guard=True, require_write=True, conflict_guard=True)))     # 교정 규칙 + 코드 가드
# 교정 규칙 파일: schema_ep5 + '## 사람 교정에서 온 규칙' 10줄
s5 = open(os.path.join(HERE, "schema_ep5.md"), encoding="utf-8").read()
open(os.path.join(HERE, "schema_ep9.md"), "w", encoding="utf-8").write(
    s5.rstrip() + "\n\n## 사람 교정에서 온 규칙 (9편 — 한 번 고친 것은 다시 틀리지 않게)\n" + "\n".join("- " + m["rule"] for m in MEMOS) + "\n")
out = {}
for cond in CONDS:
    base, schema, kw = BASE[cond]
    wdir = os.path.join(HERE, "wiki_" + NAME + "_" + cond)
    shutil.rmtree(wdir, ignore_errors=True); shutil.copytree(os.path.join(HERE, base), wdir, ignore=shutil.ignore_patterns("BUILT"))
    w = E.Wiki(wdir, schema_path=os.path.join(HERE, schema))
    before = {m["id"]: recurred(m, wiki_pages(wdir)) for m in MEMOS}      # 넣기 전 이미 있던 틀린 값(재발이 아니라 기존 오류)
    log, t0 = [], time.time()
    for m in MEMOS:
        r = E.ingest(w, os.path.join(E.RAW, m["name"]), TODAY, text_override=m["text"], name_override=m["name"], **kw)
        log.append(dict(id=m["id"], tokens=r["tokens"], pages_written=r["pages_written"], report=r["report"][:300]))
        print("[%s %-3s] pages=%s tok=%d" % (cond, m["id"], r["pages_written"], r["tokens"]), flush=True)
    after = {m["id"]: recurred(m, wiki_pages(wdir)) for m in MEMOS}
    rec = [m["id"] for m in MEMOS if set(after[m["id"]]) - set(before[m["id"]])]
    out[cond] = dict(base=base, schema=schema, before=before, after=after, recurred=rec, sec=round(time.time() - t0), tokens=sum(x["tokens"] for x in log), log=log)
    print("== %s: 넣기 전 이미 틀린 값 %d · 재발 %d/10 %s · 토큰 %d · %ds" % (cond, sum(1 for v in before.values() if v), len(rec), rec, out[cond]["tokens"], out[cond]["sec"]), flush=True)
    json.dump(out, open(os.path.join(HERE, "results", NAME + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
