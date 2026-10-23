# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
import lab
good = """계획 ... 공지 템플릿 재사용, 수신 동의 고객 1.2만 명만, 금요일 배포 금지
| 번호 | 할 일 | 먼저 끝나야 하는 번호 |
|---|---|---|
| 1 | 법무 검토로 문구 확정 | - |
| 2 | 반품 접수 시스템 설정 변경 | 1 |
| 3 | 홈페이지 공지 게시 | 1 |
| 4 | 상담원 매뉴얼 수정 | 1 |
| 5 | AI 상담봇 문구 수정 | 1 |
| 6 | 상담원 교육 | 4 |
| 7 | 고객 안내 문자 발송 | 2, 3 |"""
g = lab.grade(good)
print("정답 기대 True True True / 차례 3:", g["sms_after_legal"], g["sms_after_system"], g["web_after_legal"], g["waves"], g["template"], g["consent"], g["friday"])
bad = """| 번호 | 할 일 | 먼저 끝나야 하는 번호 |
|---|---|---|
| 1 | 고객 안내 문자 발송 | - |
| 2 | 법무 검토 | - |
| 3 | 홈페이지 공지 | - |
| 4 | 시스템 설정 변경 | 2 |"""
g = lab.grade(bad)
print("틀린 계획 기대 False False False:", g["sms_after_legal"], g["sms_after_system"], g["web_after_legal"])
