# -*- coding: utf-8 -*-
"""10편 결과의 '최종' 채점을 고친 채점기로 다시 한다(위키 폴더 wiki_<name>_<cond> 가 남아 있어야 함, API 없음). 주차별 채점은 그때 위키라 다시 못 한다.
사용: python _scratch/wiki/ops_regrade.py ep10b"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ops_grade import CFG, grade_ops, wiki_pages
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
name = sys.argv[1] if len(sys.argv) > 1 else "ep10b"
path = os.path.join(HERE, "results", name + ".json")
d = json.load(open(path, encoding="utf-8"))
for cond, r in d.items():
    wdir = os.path.join(HERE, "wiki_%s_%s" % (name, cond))
    old = r["final"]["fresh"]
    r["final"] = grade_ops(wiki_pages(wdir), CFG["today_final"])
    print("%s %s: 최신 %d → %d · 낡음 %d · 없음 %d · 지난 예정 %d" % (name, cond, old, r["final"]["fresh"], r["final"]["stale"], r["final"]["missing"], r["final"]["overdue"]))
json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
