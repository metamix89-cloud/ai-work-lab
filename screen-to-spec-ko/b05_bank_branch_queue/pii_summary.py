# -*- coding: utf-8 -*-
"""pii_probe_results.json → 표. 공개 화면 · 응답 · 익명 GET · 직원 응답의 계좌 전체 · 다른 창구 · 지점장 · 지점장 현황.
사용: python _scratch/s2s/b05_bank_branch_queue/pii_summary.py"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "pii_probe_results.json"), encoding="utf-8"))
print("| 앱 | 대기 화면 이름 | 화면 샘 | 응답 샘 | 응답 업무 | 익명 GET 샘 | 호출 창구 응답에 계좌 전체 | 다른 창구 | 지점장 상세 | 지점장 현황 | 비고 |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
names = sorted(R, key=lambda n: ("ADBC".find(n[0]) if n[0] in "ADBC" else 9, n))
total = {}
for n in names:
    r = R[n]
    ch = {c["name"]: c for c in r.get("checks", [])}
    own = ch.get("호출한 창구의 직원", {})
    other = ch.get("다른 창구의 직원", {})
    mg = ch.get("지점장이 고객 상세", {})
    sm = ch.get("지점장 현황", {})
    row = {"화면 샘": bool(r.get("screen_pii")), "응답 샘": bool(r.get("response_pii")), "응답 업무": bool(r.get("response_service")),
           "익명 샘": bool(r.get("crawl_leaks")), "계좌 전체": "계좌번호" in own.get("pii", []), "다른 창구": bool(other.get("pii")),
           "지점장 상세": bool(mg.get("pii")), "지점장 현황": bool(sm.get("pii"))}
    if n[0] in "ADBC":
        t = total.setdefault(n[0], {"n": 0})
        t["n"] += 1
        for k, v in row.items():
            t[k] = t.get(k, 0) + int(v)
        t["이름 가림"] = t.get("이름 가림", 0) + int(r.get("screen_name_form") == "가림")
        t["이름 없음"] = t.get("이름 없음", 0) + int(r.get("screen_name_form") == "없음")
    print("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
        n, r.get("screen_name_form"), ",".join(r.get("screen_pii", [])) or "—", ",".join(r.get("response_pii", [])) or "—",
        ",".join(r.get("response_service", [])) or "—", ",".join(r.get("crawl_leaks", [])) or "—", "샘" if row["계좌 전체"] else "—",
        ",".join(other.get("pii", [])) or "—", ",".join(mg.get("pii", [])) or "—", ",".join(sm.get("pii", [])) or "—",
        "; ".join(r.get("notes", []))[:80] or ("호출 못 함" if r.get("q_called") is False else "")))
print()
for c in "ADBC":
    if c in total:
        print(c, total[c])
