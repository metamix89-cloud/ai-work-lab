# -*- coding: utf-8 -*-
"""채점기(tests/test_dod.py) 먼저 시험 — 정답 앱은 9/9, 함정 앱은 정해진 테스트만 떨어져야 한다.
사용: python _scratch/s2s/05_s2s_policy_search/test_grade.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from grade_run import grade_dir   # noqa: E402

EXPECT = {
    "ref_app": {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9"},
    "trap_app": {"T1", "T8"},     # T8 은 id 순 정렬이 우연히 맞음(H-02 < H-03)
}
ok = True
for name, want in EXPECT.items():
    res = grade_dir(os.path.join(HERE, "selftest", name), os.path.join(HERE, "tests"), port=9050 + 10 * len(name))
    got = {t for t, v in res["tests"].items() if v == "pass"}
    good = got == want
    ok &= good
    print(("OK " if good else "XX ") + name, "통과 %d/9" % len(got), "" if good else "got=%s want=%s" % (sorted(got), sorted(want)))
    for t, v in sorted(res["tests"].items()):
        if v != "pass":
            print("    ", t, v, (res["detail"].get(t) or "")[:160].replace("\n", " "))
print("자가 시험", "통과" if ok else "실패")
sys.exit(0 if ok else 1)
