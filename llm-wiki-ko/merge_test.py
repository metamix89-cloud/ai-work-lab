# -*- coding: utf-8 -*-
"""write_page_keep_history 자가 시험(API 없음): 임시 위키에 이력 표 · 출처 · 상충이 있는 페이지를 쓰고, 그것을 지운 새 내용으로 덮어쓴 뒤 되살아났는지 본다.
사용: python _scratch/wiki/merge_test.py"""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
d = tempfile.mkdtemp(prefix="wiki_merge_")
w = E.Wiki(d)
old = """# 가나공급
분류: 거래처   갱신: 2026-10-26
출처: suppliers/가나공급_계약요약.md, suppliers/가나공급_단가표.csv

## 현재 값 / 요약
- 결제 조건: 월 마감, 익월 15일 현금 (출처: suppliers/가나공급_계약요약.md)

## 단가 이력 표
| 품목 | 단가 | 적용일 | 출처 |
|---|---|---|---|
| 떡볶이 소스 2kg | 73,400원 | 2026-07-01 | suppliers/가나공급_단가표.csv |
| 고추장 500g | 46,200원 | 2026-07-01 | suppliers/가나공급_단가표.csv |

## ⚠ 상충 · 확인 필요
- 메모: 10% 인상 (구매팀_메모, 등급 5) — 공문은 8%
"""
new = """# 가나공급
분류: 거래처   갱신: 2026-10-26
출처: suppliers/가나공급_공문_2026-10-15.md

## 현재 값 / 요약
- 담당자: 정 부장

## 단가 이력 표
| 품목 | 단가 | 적용일 | 출처 |
|---|---|---|---|
| 떡볶이 소스 2kg | 79,270원 | 2026-11-01 | suppliers/가나공급_공문_2026-10-15.md |
"""
w.write_page("거래처/가나공급", old)
_, kept = w.write_page_keep_history("거래처/가나공급", new)
out = w.read_page("거래처/가나공급")
print(out)
ok = all(s in out for s in ["계약요약.md", "73,400원", "46,200원", "79,270원", "메모: 10%"])
print("되살린 줄 %d · 시험 %s" % (kept, "통과" if ok else "실패"))
shutil.rmtree(d, ignore_errors=True)
sys.exit(0 if ok else 1)
