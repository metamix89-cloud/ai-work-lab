# -*- coding: utf-8 -*-
"""tally_table 도구 자가 시험: 한 주 파일을 유형별 · 유형 × 상품으로 세어 cs_counts.py 의 코드 값과 같은지 본다.
사용: python _scratch/wiki/tally_test.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
print(E.tally_table("cs/2026-W38.md", "유형"))
print()
print(E.tally_table("raw/cs/2026-W38.md", "유형", "상품").splitlines()[0])
print(E.tally_table("cs/2026-W38.md", "없는열"))
print(E.tally_table("cs/없음.md", "유형"))
