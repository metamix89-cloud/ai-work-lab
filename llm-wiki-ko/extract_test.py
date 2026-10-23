# -*- coding: utf-8 -*-
"""extract_decisions 자가 시험(API 없음): 회의록 세 개에서 결정 칸이 제대로 뽑히는지 본다.
사용: python _scratch/wiki/extract_test.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
for p in ["meetings/2026-08-04_경영회의.md", "meetings/2026-09-01_경영회의.md", "meetings/2026-09-08_구매회의.md", "meetings/2026-10-06_품질회의.md"]:
    print("==", p)
    print(E.extract_decisions(p))
