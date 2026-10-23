# -*- coding: utf-8 -*-
"""저장된 답(results/epN.json)을 고친 채점기 · 질문 규칙으로 다시 채점한다(API 재호출 없음). 바뀐 판정을 보여 주고 파일을 덮어쓴다.
사용: python _scratch/wiki/regrade.py ep1"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grade import grade_answer, grounded
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
name = sys.argv[1] if len(sys.argv) > 1 else "ep1"
qs = {q["id"]: q for q in json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))["questions"]}
path = os.path.join(HERE, "results", name + ".json")
res = json.load(open(path, encoding="utf-8"))
changed = 0
for r in res:
    if "ok" not in r:
        continue
    ok, why = grade_answer(qs[r["id"]], r["answer"])
    g = grounded(qs[r["id"]], r["answer"])
    if ok != r["ok"]:
        changed += 1
        print("%s %s t%d: %s → %s  (%s)" % (r["cond"], r["id"], r["trial"], r["ok"], ok, why or "정답"))
    r["ok"], r["why"], r["grounded"] = ok, why, g
json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("바뀐 판정 %d건, 저장: %s" % (changed, path))
