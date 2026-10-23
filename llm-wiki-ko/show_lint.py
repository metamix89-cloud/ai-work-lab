# -*- coding: utf-8 -*-
"""lint 결과 한 번(trial)의 항목을 글로 본다(원고에 인용할 실제 출력 확인용).
사용: python _scratch/wiki/show_lint.py lint_full [--trial=0] [--kw=참기름] [--orphans] [--stale]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
name = args[0]
opt = lambda k, d=None: next((a.split("=", 1)[1] for a in args if a.startswith("--%s=" % k)), d)
t = int(opt("trial", 0)); kw = opt("kw")
r = json.load(open(os.path.join(HERE, "results", name + ".json"), encoding="utf-8"))["runs"][t]["result"]
for c in r.get("conflicts", []):
    s = json.dumps(c, ensure_ascii=False)
    if kw is None or kw in s:
        print("- 상충:", s[:600])
if "--stale" in args:
    for c in r.get("stale", []):
        print("- 낡음:", json.dumps(c, ensure_ascii=False)[:300])
if "--orphans" in args:
    print("- 고아(%d):" % len(r.get("orphans", [])), ", ".join(map(str, r.get("orphans", [])))[:800])
    print("- 빠짐:", ", ".join(map(str, r.get("missing", [])))[:400])
