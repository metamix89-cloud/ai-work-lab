# CLAUDE.md — 가나다식품 「오늘의 현황판」

이 폴더의 `PRD.md` 가 요구사항이다. 이 파일은 **만드는 방법과 끝났다고 말할 조건**이다.

## 스택 (바꾸지 않는다)

- Python 3 · FastAPI · uvicorn · SQLite(표준 라이브러리 `sqlite3`) · 순수 HTML/JS/CSS.
- 외부 패키지는 `fastapi` · `uvicorn` 만. 차트 라이브러리 · CDN · 빌드 도구 · 프런트 프레임워크 금지.

## 폴더

```
main.py            FastAPI 앱 (app = FastAPI()). 시작 시 seed/*.csv → dash.db 재생성
static/index.html  화면 (JS 는 이 파일 안이나 static/app.js)
seed/              orders.csv · stock.csv · inquiries.csv  — 파일 이름 · 칸 이름을 바꾸지 않는다
tests/test_dod.py  완료 기준. 읽기만 한다. 고치거나 지우거나 건너뛰지 않는다
```

## 실행 · 검증

```
python -m uvicorn main:app --port 8000
python -m pytest tests -q
```

- `pytest` 가 **9/9 통과**해야 끝난 것이다. 통과하지 못했으면 끝났다고 말하지 않는다.
- 테스트가 `seed/` 를 자기 데이터로 바꿔 끼운다. 그래서 서버는 **시작할 때마다** CSV 를 다시 읽어야 한다(DB 를 한 번 만들고 재사용하면 틀린다).
- 테스트는 서버를 `python -m uvicorn main:app --port <PORT>` 로 띄운다. `main.py` 가 다른 포트를 고정하거나 시작할 때 시간이 오래 걸리면 실패한다.

## 하지 말 것

- PRD 8 범위 밖 기능(로그인 · 필터 · 기간 선택 · 상세 · 알림 · 자동 새로고침 · 다크 모드 · 매출 지표 · 입력 화면)을 넣지 않는다. "있으면 좋을" 것은 넣지 않는다.
- `tests/` 와 `seed/` 의 칸 이름 · 파일 이름을 바꾸지 않는다. 테스트가 실패하면 **앱을** 고친다.
- `data-testid` 이름(PRD 4 화면)을 바꾸지 않는다.
- 규칙(R1~R6)을 코드 주석이나 README 로만 적고 넘어가지 않는다. 코드가 규칙대로 계산해야 한다.

## 완료 보고 형식

마지막 답은 아래 형식으로만 한다.

```
DoD: 9/9 (또는 n/9, 실패한 T번호와 이유)
만든 파일: main.py, static/index.html, seed/*.csv
범위 밖 기능: 없음 (있으면 이름)
PRD 와 다르게 한 것: 없음 (있으면 무엇과 이유)
```
