# -*- coding: utf-8 -*-
"""채점기(tests/test_dod.py) 먼저 시험 — 정답 앱은 9/9, 함정 앱은 정해진 테스트만 통과해야 한다.
함정 앱의 실수: 만료 없음 · 본인 승인 허용 · 검토 건너뛰고 승인 · 상충 검사 없음 · 점검 항목 비어도 신청 · 현황판 상충 경고 없음.
사용: python _scratch/s2s/b06_work_permit/test_grade.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from grade_run import grade_dir   # noqa: E402

EXPECT = {
    "ref_app": {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9"},
    # 함정: T2 상충 쌍 없음 · T3 항목 누락 201 · T4 본인 승인 200 · T5 만료 허가 시작 200 · T6 상충 승인 200 · T8 '검토 전 승인' 이 409 가 아니라… (w1 승인은 403 이라 통과) → T8 은 '없는 구역 + 항목 누락' 은 404 로 통과
    # T7 은 T6 에서 WP-0103 이 승인되므로 그대로 통과. T9 는 화면이 최소라 떨어진다.
    "trap_app": {"T1", "T7", "T8"},
}
ok = True
for name, want in EXPECT.items():
    res = grade_dir(os.path.join(HERE, "selftest", name), os.path.join(HERE, "tests"), port=9300 + 10 * len(name))
    got = {t for t, v in res["tests"].items() if v == "pass"}
    good = got == want
    ok &= good
    print(("OK " if good else "XX ") + name, "통과 %d/9" % len(got), "" if good else "got=%s want=%s" % (sorted(got), sorted(want)))
    for t, v in sorted(res["tests"].items()):
        if v != "pass":
            print("    ", t, v, (res["detail"].get(t) or "")[:200].replace("\n", " "))
print("자가 시험", "통과" if ok else "실패")
sys.exit(0 if ok else 1)
