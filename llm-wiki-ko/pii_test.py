# -*- coding: utf-8 -*-
"""11편 v2 코드 가림 자가 시험(API 없음): engine.pii_mask 가 planted P1~P10 중 형식 있는 것을 가리고, 형식 없는 것은 못 가린다는 것을 보인다.
사용: python _scratch/wiki/pii_test.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")
cases = [("P1 전화", "고객 휴대전화 010-0000-0011 로 연락", "010-0000-0011", True),
         ("P4 주민번호", "신분증 사본(900101-1******) 스캔본", "900101-1", True),
         ("P5 담당자 전화", "정 부장, 개인 휴대전화 010-0000-0012", "010-0000-0012", True),
         ("P7 비밀번호", "사내 시스템 초기 비밀번호는 Ganada!2026이며", "Ganada!2026", True),
         ("P3 연봉", "오 과장 연봉 5,200 이라던데", "5,200", True),
         ("P9 사번", "물류팀 최○○ (사번 L-017) 인사위 회부 예정", "L-017", True),
         ("P9 이름(형식 없음)", "물류팀 최○○ 인사위 회부 예정", "최○○", False),
         ("P10 신제품 코드명(형식 없음)", "프로젝트 K 2027-02-01 출시", "프로젝트 K", False),
         ("정상 날짜 · 금액은 안 가림", "2026-10-26 단가 73,400원, 2026-W38 주", "73,400", False)]
bad = 0
for name, text, sig, should_mask in cases:
    out, n = E.pii_mask(text)
    masked = sig not in out
    ok = masked == should_mask
    print(("OK  " if ok else "!!  ") + "%-24s → %s" % (name, out[:60])); bad += not ok
raw_n = sum(E.pii_mask(E.read(f))[1] for f in E.raw_files())
print("원본 57개에서 코드가 가린 자리: %d곳" % raw_n)
print("자가 시험:", "통과" if not bad else "실패 %d" % bad)
sys.exit(1 if bad else 0)
