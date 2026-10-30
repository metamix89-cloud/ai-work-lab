# 두둑은행 방문 예약 · 대기 현황판
실행: `pip install -r requirements.txt` → `uvicorn main:app` → http://127.0.0.1:8000
(첫 실행 시 가상 데이터 자동 생성. 초기화는 duduk.db 삭제)

| 화면 | 주소 | 로그인(데모 PIN) |
|---|---|---|
| 고객 예약/번호표/도착확인 | / | - |
| 대기 화면(모니터) | /display.html | - |
| 창구 직원 | /staff.html | 창구1~4 = 1111/2222/3333/4444 |
| 지점장 | /manager.html | 9999 |

PIN은 환경변수 DUDUK_STAFF_PINS("a,b,c,d"), DUDUK_MANAGER_PIN 으로 교체.
데모 예약번호: 100001~100004 (100003 은 곧 도착 가능한 예약).
