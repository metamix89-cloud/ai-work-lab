# -*- coding: utf-8 -*-
"""6편 lint 결과 표: results/lint_*.json 여러 개를 한 표로(돌린 횟수별 값 · 평균), 항목별 찾은 횟수, 미매칭(오탐 후보) 글.
사용: python _scratch/wiki/lint_table.py lint_full lint_ep5c lint_full_v2 lint_ep5c_v2 [--items] [--unmatched]"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
names = [a for a in args if not a.startswith("--")]
print("%-14s %5s %7s %9s %9s %9s %7s %7s  %-28s %9s" % ("결과", "범위", "두값있음", "찾음(합)", "판단맞음", "보고(합)", "미매칭", "횟수", "고아 코드/lint/맞춤/오탐", "토큰/회"))
for n in names:
    d = json.load(open(os.path.join(HERE, "results", n + ".json"), encoding="utf-8"))
    rs = d["runs"]; k = len(rs)
    g0 = rs[0]["grade"]
    orph = [r["grade"].get("orphans") for r in rs if r["grade"].get("orphans")]
    o = "%d/%s/%s/%s" % (orph[0]["code"], "·".join(str(x["lint"]) for x in orph), "·".join(str(x["hit"]) for x in orph), "·".join(str(x["false"]) for x in orph)) if orph else "-"
    print("%-14s %5d %7d %9s %9s %9s %7s %7d  %-28s %9.0f" % (
        n, g0["n"], g0["both"], "·".join(str(r["grade"]["found"]) for r in rs), "·".join(str(r["grade"]["judged"]) for r in rs),
        "·".join(str(r["grade"]["reported"]) for r in rs), "·".join(str(len(r["grade"]["unmatched"])) for r in rs), k, o, sum(r["tokens"] for r in rs) / k))
    if "--items" in args:
        ids = [p["id"] for p in g0["items"]]
        found = {i: sum(1 for r in rs for p in r["grade"]["items"] if p["id"] == i and p["found"]) for i in ids}
        judged = {i: sum(1 for r in rs for p in r["grade"]["items"] if p["id"] == i and p["judged_right"]) for i in ids}
        both = {p["id"]: p["both_in_wiki"] for p in g0["items"]}
        print("   " + "  ".join("%s:%s%d/%d" % (i, "" if both[i] else "(한쪽값)", found[i], judged[i]) for i in ids))
    if "--unmatched" in args:
        for r in rs:
            for u in r["grade"]["unmatched"]:
                print("   [t%d 미매칭] %s" % (r["trial"], u))
