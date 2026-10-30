# 두둑은행 방문 예약 · 대기 현황판

실행: `pip install -r requirements.txt` → `python -m uvicorn main:app --port 8000` → http://localhost:8000
(첫 실행 시 `queue.db` 와 가상 데이터 자동 생성. 초기화하려면 `queue.db` 삭제)

| 화면 | 주소 | 비고 |
|---|---|---|
| 고객 예약/번호표/도착확인 | /static/index.html | |
| 지점 대기 모니터 | /static/display.html | 이름 일부(김*수)·번호표만 표시, 3초 갱신 |
| 창구 직원 | /static/teller.html | PIN 1111 (`TELLER_PIN`) |
| 지점장 | /static/manager.html | PIN 9999 (`MANAGER_PIN`) |

규칙: 예약 고객은 도착 확인 후 현장 고객보다 먼저 호출(예약시각 순). 예약시각+15분 내 미도착 시 자동 노쇼, 호출 후 미응답은 창구에서 노쇼 처리.
영업시간은 `BANK_OPEN`/`BANK_CLOSE`(기본 09:00~16:00)로 조정. 데모용 PIN·가상 데이터이므로 실제 운영 전 인증/HTTPS/개인정보 암호화 필요.
