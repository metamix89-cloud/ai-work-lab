# CLAUDE.md — 한빛요양병원 「당직 순번표」

이 폴더의 `PRD.md` 가 요구사항이다. 이 파일은 **만드는 방법과 끝났다고 말할 조건**이다.

## 스택 (바꾸지 않는다)

- Python 3 · FastAPI · uvicorn · SQLite(표준 라이브러리 `sqlite3`) · 순수 HTML/JS/CSS.
- 외부 패키지는 `fastapi` · `uvicorn` 만. 알고리즘은 표준 라이브러리로. CDN · 빌드 도구 · 프런트 프레임워크 금지.

## 폴더

```
main.py            FastAPI 앱 (app = FastAPI()). 시작 시 seed/*.csv → duty.db 재생성. 생성 알고리즘도 여기(또는 roster.py)
static/index.html  화면 (JS 는 이 파일 안이나 static/app.js)
seed/              staff.csv · unavailable.csv · roster.csv — 파일 이름 · 칸 이름을 바꾸지 않는다
tests/test_dod.py  완료 기준. 읽기만 한다. 고치거나 지우거나 건너뛰지 않는다
```

## 실행 · 검증

```
python -m uvicorn main:app --port 8000
python -m pytest tests -q
```

- `pytest` 가 **9/9 통과**해야 끝난 것이다. 통과하지 못했으면 끝났다고 말하지 않는다.
- 테스트가 `seed/` 를 자기 데이터로 바꿔 끼우고 서버를 새로 띄운다. 서버는 **시작할 때마다** CSV 를 다시 읽어야 한다.
- 생성 결과는 **R1~R5 를 모두** 만족해야 한다. 그럴듯하게 돌아가며 채우는 것(라운드 로빈)은 제외일 · 연속 · 주말 공평에서 깨진다. 생성 뒤 코드가 스스로 R1~R5 를 검사하고, 못 만들면 422 를 내라.
- 바꾸기 · 확정 검사는 **서버(API)** 가 한다. 화면은 안내일 뿐이고, 테스트는 API 를 직접 부른다.

## 하지 말 것

- PRD 8 범위 밖 기능(로그인 · 2교대 · 희망 근무 · 바꾸기 승인 흐름 · 공휴일 가중치 · 알림 · 인쇄 · 여러 병동 · 다크 모드)을 넣지 않는다.
- `tests/` 와 `seed/` 의 칸 이름 · 파일 이름을 바꾸지 않는다. 테스트가 실패하면 **앱을** 고친다.
- `data-testid` · `data-date` · `data-name` 이름(PRD 4 화면)과 거부 응답의 상태 코드(400 · 409 · 422) · `detail` 문구(PRD 5 · 6)를 바꾸지 않는다.
- 무작위(random)로 채우고 규칙 검사를 안 하는 생성을 하지 않는다. 무작위를 쓰면 시드를 고정하고 생성 뒤 검사한다.

## 완료 보고 형식

마지막 답은 아래 형식으로만 한다.

```
DoD: 9/9 (또는 n/9, 실패한 T번호와 이유)
만든 파일: main.py, static/index.html, seed/*.csv
범위 밖 기능: 없음 (있으면 이름)
PRD 와 다르게 한 것: 없음 (있으면 무엇과 이유)
```
