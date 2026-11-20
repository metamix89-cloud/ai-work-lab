# 뚝딱건설 위험 작업 허가서

실행: `pip install -r requirements.txt` 후 `python -m uvicorn app.main:app --port %PORT%` (예: 9640) → 브라우저에서 `/` 접속.
첫 실행 때 `data/permits.db` 가 만들어지고 가상 데이터가 들어간다. 지우면 초기화된다.
테스트: `pip install -r requirements-dev.txt && python -m pytest -q`

화면 오른쪽 위에서 사용자를 고르면 역할이 바뀐다(데모용 간이 로그인, 실제 인증 없음).
규칙 구현은 `app/rules.py`, 상태 전이·권한은 `app/main.py`.
