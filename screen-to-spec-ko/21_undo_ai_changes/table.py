# -*- coding: utf-8 -*-
"""results.json → 조건별 요약(summary.json) + 표. 영상 · 설명란의 숫자는 여기서만 옮긴다.
사용: python _scratch/s2s/21_undo_ai_changes/table.py"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
summary = {"base": {"dod": R["base"]["dod"]},
           "broken": {"dod": R["broken"]["dod"], "dod_fail": R["broken"]["dod_fail"], "same_bytes": R["broken"]["same_bytes"],
                      "changed": {f: v for f, v in R["broken"]["per_file"].items() if v["state"] != "same"},
                      "cost": R["broken"]["build"]["total_cost_usd"], "wall_s": R["broken"]["build"]["wall_s"]}}
print("| 조건 | 회 | 원본과 똑같은 파일(6개 중) | 6개 다 같은 실행 | 완료 기준(9개 중) | 아무것도 안 고친 실행 | git 명령 | 시간(초) | 비용 |")
print("|---|---|---|---|---|---|---|---|---|")
for cond in ("U1", "U2", "U3"):
    names = sorted(n for n in R if n.startswith(cond + "_"))
    rows = [R[n] for n in names]
    untouched = [n for n in names if all(R[n]["per_file"][f] == R["broken"]["per_file"][f] for f in R["broken"]["per_file"])]
    gits = {}
    for r in rows:
        for c in r.get("git_cmds") or []:
            for word in ("git stash", "git restore", "git checkout", "git reset", "git diff", "git log", "git status"):
                if word in c:
                    gits.setdefault(word, set()).add(id(r))
    s = {"runs": names, "same_bytes": [r["same_bytes"] for r in rows], "all_same": sum(r["same_bytes"] == r["total_files"] for r in rows),
         "dod": [r["dod"] for r in rows], "untouched": untouched, "git_runs": {k: len(v) for k, v in gits.items()},
         "wall_s": [r["build"]["wall_s"] for r in rows], "cost": round(sum(r["build"]["total_cost_usd"] or 0 for r in rows), 3),
         "turns": [r["build"]["num_turns"] for r in rows]}
    summary[cond] = s
    print("| %s | %d | %s | %d / %d | %s | %s | %s | %.0f~%.0f | $%.2f |" % (
        cond, len(rows), " · ".join(map(str, s["same_bytes"])), s["all_same"], len(rows), " · ".join(map(str, s["dod"])),
        ", ".join(untouched) or "0", s["git_runs"] or "-", min(s["wall_s"]), max(s["wall_s"]), s["cost"]))
summary["total_cost"] = round(summary["broken"]["cost"] + sum(summary[c]["cost"] for c in ("U1", "U2", "U3")), 3)
print("망친 상태: 완료 기준 %d/9 (떨어진 것 %s) · 원본과 같은 파일 %d/6 · 비용 합계 $%.2f" % (
    summary["broken"]["dod"], ",".join(summary["broken"]["dod_fail"]), summary["broken"]["same_bytes"], summary["total_cost"]))
json.dump(summary, open(os.path.join(HERE, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
