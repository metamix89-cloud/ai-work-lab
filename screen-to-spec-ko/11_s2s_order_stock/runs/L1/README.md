# 가나다식품 주문 · 재고 백오피스

## 설치
    python -m pip install fastapi==0.161.1 uvicorn==0.53.0

## 실행
    python -m uvicorn main:app --port 8000

환경 변수 `PORT` (기본 8000) 가 있으면 `python main.py` 는 그 포트로 뜬다.
서버는 시작할 때마다 `seed/*.csv` 로 `backoffice.db` 를 새로 만든다.

## 시험
    python -m pytest tests -q

(시험은 playwright 가 필요하다.) 재고는 확정할 때 줄고 확정 주문을 취소할 때 돌아온다.
요청 처리가 한 번에 하나씩 돌게 두어 동시 확정에도 재고가 0 미만이 되지 않는다.
