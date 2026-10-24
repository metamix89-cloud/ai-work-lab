# -*- coding: utf-8 -*-
"""그 편 테스트(tests/test_dod.py)의 고정 데이터를 앱 폴더의 seed/ 에 써 준다 — 자가 시험용 정답 · 함정 앱의 표본 시드.
사용: python _scratch/s2s/tools/write_fixture_seed.py <lab_dir> <app_dir> [<app_dir> ...]"""
import importlib.util
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
lab = os.path.abspath(sys.argv[1])
for app in sys.argv[2:]:
    app = os.path.abspath(app)
    os.environ["APP_DIR"] = app
    spec = importlib.util.spec_from_file_location("dod_%d" % abs(hash(app)), os.path.join(lab, "tests", "test_dod.py"))
    dod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dod)
    dod.write_seed()
    shutil.rmtree(os.path.join(app, "seed_backup"), ignore_errors=True)
    print(app, "→", sorted(os.listdir(os.path.join(app, "seed"))))
