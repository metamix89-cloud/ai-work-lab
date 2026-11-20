# -*- coding: utf-8 -*-
"""실행별 AI 의 마지막 보고만 이어서 본다. 사용: python _scratch/s2s/20_feature_regression/show_reports.py M1_4 M1_5 ..."""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
for name in sys.argv[1:]:
    b = json.load(open(os.path.join(HERE, "runs", name, "build.json"), encoding="utf-8"))
    print("=====", name, "\n" + (b.get("result") or ""), "\n")
