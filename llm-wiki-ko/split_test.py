# -*- coding: utf-8 -*-
"""split_articles 자가 시험(API 없음): 규정집이 36조로 쪼개지고, 조항이 없는 파일은 빈 목록인지.
사용: python _scratch/wiki/split_test.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
parts = E.split_articles(os.path.join(E.RAW, "policies", "사규_2026.md"))
print("조항 %d개" % len(parts))
print(parts[1][0]); print(parts[1][1][:300]); print("…")
print(parts[-1][0]); print(parts[-1][1][-200:])
print("개정 공지 쪼개짐:", len(E.split_articles(os.path.join(E.RAW, "policies", "개정공지_2026-10-01_법인카드.md"))))
