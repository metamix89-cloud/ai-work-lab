# 두둑은행 방문 예약 · 대기 현황판

    pip install -r requirements.txt
    python -m uvicorn app.main:app --port 8000

첫 실행 때 가상 데이터가 들어갑니다. 초기화하려면 `dudug.db`를 지우고 다시 실행하세요.

| 화면 | 주소 | 로그인 |
|---|---|---|
| 고객(예약 · 도착 확인 · 번호표) | `/` | 없음 |
| 대기 화면(모니터) | `/display` | 없음 (번호 · 가린 이름 · 창구만 표시) |
| 창구 직원 | `/teller` | 창구 1~4 → PIN 1111 / 2222 / 3333 / 4444 |
| 지점장 | `/manager` | PIN 9999 |

PIN은 데모 값입니다. 운영 전 `DUDUG_TELLER_PINS="a,b,c,d"`, `DUDUG_MANAGER_PIN` 환경변수로 바꾸세요.

테스트: `python -m pytest -q`
