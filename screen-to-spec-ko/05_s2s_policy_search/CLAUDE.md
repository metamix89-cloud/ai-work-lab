# CLAUDE.md — 다온소프트 「사내 규정 검색」

이 폴더의 `PRD.md` 가 요구사항이다. 이 파일은 **만드는 방법과 끝났다고 말할 조건**이다.

## 스택 (바꾸지 않는다)

- Python 3 · FastAPI · uvicorn · SQLite(표준 라이브러리 `sqlite3`) · 순수 HTML/JS/CSS.
- 외부 패키지는 `fastapi` · `uvicorn` 만. 검색 엔진 · 임베딩 · LLM · 형태소 분석기 금지. CDN · 빌드 도구 · 프런트 프레임워크 금지.

## 폴더

```
main.py            FastAPI 앱 (app = FastAPI()). 시작 시 seed/clauses.csv → policy.db 재생성
static/index.html  화면 (JS 는 이 파일 안이나 static/app.js)
seed/clauses.csv   규정 조항 — 파일 이름 · 칸 이름을 바꾸지 않는다
tests/test_dod.py  완료 기준. 읽기만 한다. 고치거나 지우거나 건너뛰지 않는다
```

## 실행 · 검증

```
python -m uvicorn main:app --port 8000
python -m pytest tests -q
```

- `pytest` 가 **9/9 통과**해야 끝난 것이다. 통과하지 못했으면 끝났다고 말하지 않는다.
- 테스트가 `seed/` 를 자기 데이터로 바꿔 끼우고 서버를 새로 띄운다. 서버는 **시작할 때마다** CSV 를 다시 읽어야 한다.
- 검색의 규칙(현재 조항만 · AND · 없으면 없음 · 정렬)은 **서버(API)** 가 지킨다. 화면은 받은 대로 그린다. 테스트는 API 를 직접 부른다.

## 하지 말 것

- PRD 8 범위 밖 기능(로그인 · 규정 편집 화면 · 자연어 답변 · 유사어 · 오타 교정 · 동의어 · PDF · 검색 로그 · 즐겨찾기 · 다크 모드)을 넣지 않는다. "비슷한 결과라도 보여 주면 친절할 텐데" 는 R4 위반이다.
- `tests/` 와 `seed/` 의 칸 이름 · 파일 이름을 바꾸지 않는다. 테스트가 실패하면 **앱을** 고친다.
- `data-testid` 이름(PRD 4 화면)과 거부 응답의 상태 코드(400 · 404) · `detail` 문구를 바꾸지 않는다.
- 개정 전 조항을 검색 결과에 섞지 않는다. 화면에서 '접기' 로 숨기는 것이 아니라 **API 결과에서 빠져야** 한다.

## 완료 보고 형식

마지막 답은 아래 형식으로만 한다.

```
DoD: 9/9 (또는 n/9, 실패한 T번호와 이유)
만든 파일: main.py, static/index.html, seed/clauses.csv
범위 밖 기능: 없음 (있으면 이름)
PRD 와 다르게 한 것: 없음 (있으면 무엇과 이유)
```
