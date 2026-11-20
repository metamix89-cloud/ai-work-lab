# -*- coding: utf-8 -*-
"""ep097 채점기 먼저 시험 — 바탕 앱은 기존 9/9 · 새 0/3, 정답 앱 둘(저장 구조가 다름)은 12/12, 함정 앱은 기존 9/9 · 새 0/3.
사용: python _scratch/s2s/20_feature_regression/test_grade.py"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from grade_run import grade_dir   # noqa: E402

OLD = {"T%d" % i for i in range(1, 10)}
NEW = {"T10", "T11", "T12"}
EXPECT = {
    "base": OLD,
    "selftest/ref_a": OLD | NEW,
    "selftest/ref_b": OLD | NEW,
    "selftest/trap": OLD,
}
ok = True
for k, (name, want) in enumerate(EXPECT.items()):
    res = grade_dir(os.path.join(HERE, *name.split("/")), os.path.join(HERE, "tests"), port=9150 + 10 * k)
    got = {t for t, v in res["tests"].items() if v == "pass"}
    good = got == want
    ok &= good
    print(("OK " if good else "XX ") + name, "통과 %d/12" % len(got), "" if good else "got=%s want=%s" % (sorted(got), sorted(want)))
    for t, v in sorted(res["tests"].items(), key=lambda x: int(x[0][1:])):
        if v != "pass":
            print("    ", t, v, (res["detail"].get(t) or "")[:200].replace("\n", " "))
print("자가 시험", "통과" if ok else "실패")
sys.exit(0 if ok else 1)
