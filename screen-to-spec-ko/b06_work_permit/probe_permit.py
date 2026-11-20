# -*- coding: utf-8 -*-
"""PRD 가 정하지 않은 자리를 결과물(B · C)과 정답 앱에 같은 요청으로 찔러 본다 — tools/probe_cases.probe 를 쓰되
고정 데이터에 더하는 행의 시각이 '지금' 기준이라 json 대신 여기서 만든다.
사용: python _scratch/s2s/b06_work_permit/probe_permit.py [runs/B1 runs/C2 ...]  (없으면 selftest/ref_app + runs/B* + runs/C*)"""
import glob
import importlib.util
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from probe_cases import probe   # noqa: E402

spec = importlib.util.spec_from_file_location("dod", os.path.join(HERE, "tests", "test_dod.py"))
dod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dod)
h = dod.at_h
ADD = {"PERMITS": [
    ("WP-0201", "confined", "Z3", "w1", h(-1), h(2), "approved", "C1|C2|C3", "s1", "m1", h(-9), "", ""),      # 만료된 밀폐 — 상충의 상대가 되나?
    ("WP-0202", "hot", "Z3", "w2", h(0), h(1), "reviewed", "F1|F2|F3", "s1", "", "", "", ""),               # 만료된 밀폐 위에 화기 승인
    ("WP-0203", "hot", "Z3", "w1", h(0), h(2), "reviewed", "F1|F2|F3", "s1", "", "", "", ""),               # 화기 + 화기 같은 구역 겹침
    ("WP-0204", "height", "Z1", "w2", h(-5), h(-3), "reviewed", "H1|H2|H3", "s1", "", "", "", ""),          # 작업 시간이 이미 끝난 신청을 승인?
    ("WP-0205", "height", "Z1", "w2", h(3), h(5), "approved", "H1|H2|H3", "s1", "m1", dod.today_or(0.5), "", ""),   # 계획 시작 전인데 작업 시작?
    ("WP-0206", "height", "Z2", "w2", h(-9), h(-1), "started", "H1|H2|H3", "s1", "m1", h(-9), h(-8), ""),   # 작업 중인데 만료 — 종료는 되나? 상태는?
]}
CASES = [
    {"name": "만료된 밀폐 위에 화기 승인 (0202)", "method": "POST", "path": "api/permits/WP-0202/approve", "body": {"user": "m1"}},
    {"name": "화기 + 화기 같은 구역 겹침 승인 (0203)", "method": "POST", "path": "api/permits/WP-0203/approve", "body": {"user": "m1"}},
    {"name": "작업 시간 지난 신청 승인 (0204)", "method": "POST", "path": "api/permits/WP-0204/approve", "body": {"user": "m1"}},
    {"name": "계획 시작 3시간 전에 작업 시작 (0205)", "method": "POST", "path": "api/permits/WP-0205/start", "body": {"user": "w2"}},
    {"name": "작업 중 만료 — 상태 (0206)", "method": "GET", "path": "api/permits/WP-0206?viewer=w2", "pick": "status"},
    {"name": "작업 중 만료 — 신청자 종료 (0206)", "method": "POST", "path": "api/permits/WP-0206/close", "body": {"user": "w2"}},
    {"name": "같은 항목 두 번 보낸 신청", "method": "POST", "path": "api/permits",
     "body": {"user": "w1", "work_type": "height", "zone_id": "Z1", "start_at": h(1), "end_at": h(2), "checked": ["H1", "H1", "H2", "H3"]}},
    {"name": "항목에 다른 종류 것이 섞임 (H + F1)", "method": "POST", "path": "api/permits",
     "body": {"user": "w1", "work_type": "height", "zone_id": "Z1", "start_at": h(1), "end_at": h(2), "checked": ["H1", "H2", "H3", "F1"]}},
    {"name": "작업 시간 24시간짜리 신청", "method": "POST", "path": "api/permits",
     "body": {"user": "w1", "work_type": "height", "zone_id": "Z1", "start_at": h(0), "end_at": h(24), "checked": ["H1", "H2", "H3"]}},
]


def main():
    apps = sys.argv[1:] or [os.path.join(HERE, "selftest", "ref_app")] + sorted(glob.glob(os.path.join(HERE, "runs", "B*"))) + sorted(glob.glob(os.path.join(HERE, "runs", "C*")))
    port = 9700
    for app in apps:
        print("===", os.path.basename(os.path.normpath(app)))
        for name, st, detail in probe(os.path.abspath(app), HERE, CASES, port, ADD):
            print("  %-40s %s  %s" % (name, st, detail))
        port += 1


if __name__ == "__main__":
    main()
