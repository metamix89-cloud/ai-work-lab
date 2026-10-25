# 부릉부릉렌터카 반납 점검표

```
pip install -r requirements.txt
python -m uvicorn main:app --port 8000      # http://127.0.0.1:8000
python -m pytest -q tests
```

첫 실행 시 `data/app.db`와 가상 데이터가 자동 생성됨(지우면 초기화). 데모 계정(비밀번호 `demo1234`):
직원 `staff1`·`staff2`, 고객 `kim`·`lee`·`park`.

- 요금 규칙은 `pricing.py` 상단 상수/함수에 있음(DB·HTTP 무관, 테스트로 경계값 검증).
- 반납 시각은 한국 시간(KST) 기준, 금액은 정수 원.
- 데모용이므로 운영 시에는 HTTPS(쿠키 `secure`), 비밀번호 변경, 로그인 시도 제한의 영속화 필요.
