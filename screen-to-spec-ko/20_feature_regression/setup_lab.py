# -*- coding: utf-8 -*-
"""ep097 랩 준비 — 02_s2s_meeting_room 의 9/9 완성본(runs/C1)을 바탕 앱(base/)으로 복사하고, 기존 완료 기준 테스트를 tests/ 로 가져온다.
사용: python _scratch/s2s/20_feature_regression/setup_lab.py"""
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "02_s2s_meeting_room")

base = os.path.join(HERE, "base")
if not os.path.isdir(base):
    shutil.copytree(os.path.join(SRC, "runs", "C1"), base,
                    ignore=shutil.ignore_patterns("build.json", "*.db", "__pycache__", ".pytest_cache", "seed_backup", "_grader"))
os.makedirs(os.path.join(HERE, "tests"), exist_ok=True)
dst = os.path.join(HERE, "tests", "test_dod.py")
if not os.path.exists(dst):
    shutil.copy(os.path.join(SRC, "tests", "test_dod.py"), dst)
for root, _, files in os.walk(base):
    for f in files:
        print(os.path.relpath(os.path.join(root, f), HERE))
