# 가나다식품 주문 · 재고 백오피스

설치: `pip install fastapi uvicorn`
실행: `python -m uvicorn main:app --port 8000` (또는 `python main.py`, 환경 변수 `PORT`, 기본 8000)
시험: `python -m pytest tests -q`

서버는 시작할 때마다 `seed/*.csv` 로 `backoffice.db` 를 새로 만든다.
