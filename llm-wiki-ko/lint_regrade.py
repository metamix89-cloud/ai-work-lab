# -*- coding: utf-8 -*-
"""저장된 lint 결과(results/lint_*.json)를 고친 채점기로 다시 채점한다(API 재호출 없음). 바뀐 '찾음' 수를 보여 주고 덮어쓴다.
사용: python _scratch/wiki/lint_regrade.py lint_full lint_ep5c ..."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
from lint_grade import grade_lint
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
for name in sys.argv[1:]:
    path = os.path.join(HERE, "results", name + ".json")
    d = json.load(open(path, encoding="utf-8"))
    w = E.Wiki(os.path.join(HERE, d["wiki"])); text = w.all_text()
    for r in d["runs"]:
        old = r["grade"]["found"]
        r["grade"] = grade_lint(r["result"], text, groups=d.get("groups"), wdir=os.path.join(HERE, d["wiki"]))
        print("%s t%d 찾음 %d → %d · 판단 %d · 미매칭 %d" % (name, r["trial"], old, r["grade"]["found"], r["grade"]["judged"], len(r["grade"]["unmatched"])))
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
