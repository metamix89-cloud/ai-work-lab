# -*- coding: utf-8 -*-
"""실행의 마지막 답(build.json result)과 비용 · 턴을 보여 준다.
사용: python _scratch/s2s/21_undo_ai_changes/show_report.py broken U1_1 ...   (이름 없으면 전부)"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
names = sys.argv[1:] or ["broken"] + sorted(os.path.basename(d) for d in glob.glob(os.path.join(HERE, "runs", "*")))
for n in names:
    b = os.path.join(HERE, n if n == "broken" else os.path.join("runs", n), "build.json")
    if not os.path.exists(b):
        print("==", n, "없음")
        continue
    j = json.load(open(b, encoding="utf-8"))
    print("== %s rc=%s 턴=%s %.0f초 $%.3f 격리=%s" % (n, j.get("rc"), j.get("num_turns"), j.get("wall_s") or 0, j.get("total_cost_usd") or 0,
                                                 json.dumps({k: v for k, v in (j.get("isolation") or {}).items() if v and k != "transcript"}, ensure_ascii=False)[:300]))
    for k in ("git_before", "git_after"):
        if j.get(k):
            print("  %s: %s" % (k, json.dumps(j[k], ensure_ascii=False)))
    print(j.get("result") or j.get("stdout_tail") or j.get("stderr_tail"))
