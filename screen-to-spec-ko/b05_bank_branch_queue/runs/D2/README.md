# 두둑은행 방문 예약 · 대기 현황판

    pip install -r requirements.txt
    python -m uvicorn app.main:app --port 8000

http://localhost:8000 — 첫 실행 때 가상 데이터가 자동으로 들어갑니다 (`duduk.db` 를 지우면 초기화).
데모 PIN: 창구 1~4 = 1111/2222/3333/4444, 지점장 = 9999
(환경변수 `DUDUK_PIN_C1`..`C4`, `DUDUK_PIN_MANAGER` 로 변경).
테스트: `python -m pytest tests`
