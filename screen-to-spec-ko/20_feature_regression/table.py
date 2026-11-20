# -*- coding: utf-8 -*-
"""summary.json 을 표로 — 원고 · 설명란의 숫자는 여기서만 옮긴다.
사용: python _scratch/s2s/20_feature_regression/table.py"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "summary.json"), encoding="utf-8"))
print("실행   기존  새(엄격) 새(자기이름) 코드바뀜 칸바뀜 파일 +줄/-줄  pytest 서버 턴  초   $    격리")
tot = {}
for name in sorted(S):
    s = S[name]
    b = json.load(open(os.path.join(HERE, "runs", name, "build.json"), encoding="utf-8"))
    iso = b.get("isolation") or {}
    warn = [k for k in ("foreign_ports", "kill_by_name", "outside_refs") if iso.get(k)]
    own = s.get("new_pass_own", s["new_pass_strict"] if name.startswith("M3") else "-")
    print("%-6s %d/9   %d/3      %s/3        %d       %d     %d   +%d/-%d   %2d    %d   %2s %4.0f %.2f  %s" % (
        name, s["old_pass"], s["new_pass_strict"], own, len(s.get("behavior_status_changed", [])), len(s.get("behavior_shape_changed", [])),
        len(s["changed"]) + len(s["added"]), s["lines_added"], s["lines_removed"], s["pytest_runs"], s["server_runs"], s["turns"], s["wall_s"] or 0,
        s["cost"] or 0, warn or ""))
    c = name[:2]
    t = tot.setdefault(c, dict(n=0, cost=0.0, old=[], own=[], code=0, wall=[]))
    t["n"] += 1
    t["cost"] += s["cost"] or 0
    t["old"].append(s["old_pass"])
    t["own"].append(own)
    t["code"] += 1 if s.get("behavior_status_changed") else 0
    t["wall"].append(round(s["wall_s"] or 0))
for c, t in tot.items():
    print(c, "회", t["n"], "· 기존", t["old"], "· 새(자기 이름)", t["own"], "· 기존 동작의 상태 코드가 바뀐 실행", t["code"], "· 시간", t["wall"], "· $%.2f" % t["cost"])
print("본 실험 합계 $%.2f" % sum(t["cost"] for t in tot.values()))
bad = 0.0
for p in glob.glob(os.path.join(HERE, "runs_contaminated_plugin", "*", "build.json")):
    bad += json.load(open(p, encoding="utf-8")).get("total_cost_usd") or 0
print("버린 첫 9회(플러그인 오염) $%.2f" % bad)
