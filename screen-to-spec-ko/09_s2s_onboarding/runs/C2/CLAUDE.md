# CLAUDE.md — 다온소프트 「신입사원 온보딩 교육」

이 폴더의 `PRD.md` 가 요구사항이다. 이 파일은 **만드는 방법과 끝났다고 말할 조건**이다.

## 스택 (바꾸지 않는다)

- Python 3 · FastAPI · uvicorn · SQLite(표준 라이브러리 `sqlite3`) · 순수 HTML/JS/CSS.
- 외부 패키지는 `fastapi` · `uvicorn` 만. CDN · 빌드 도구 · 프런트 프레임워크 금지.

## 폴더

```
main.py            FastAPI 앱 (app = FastAPI()). 시작 시 seed/*.csv → onboard.db 재생성
static/index.html  화면 (JS 는 이 파일 안이나 static/app.js)
seed/              users · lessons · questions · progress · attempts .csv — 파일 이름 · 칸 이름 · 형식(PRD 5 표)을 바꾸지 않는다
tests/test_dod.py  완료 기준. 읽기만 한다. 고치거나 지우거나 건너뛰지 않는다
```

## 실행 · 검증

```
python -m uvicorn main:app --port 8000
python -m pytest tests -q
```

- `pytest` 가 **9/9 통과**해야 끝난 것이다. 통과하지 못했으면 끝났다고 말하지 않는다.
- 테스트가 `seed/` 를 자기 데이터로 바꿔 끼우고 서버를 새로 띄운다. 서버는 **시작할 때마다** CSV 를 다시 읽어야 한다.
- 순서 · 채점 · 응시 횟수 · 권한은 **서버(API)** 가 지킨다. 화면에서 버튼을 숨기는 건 안내일 뿐이고, 테스트는 API 를 직접 부른다.

## 하지 말 것

- PRD 8 범위 밖 기능(로그인 · 편집 화면 · 동영상 · 재응시 허용 · 수료증 PDF · 알림 · 문항 섞기 · **오답 해설** · 차트 · 다크 모드)을 넣지 않는다.
- **정답을 화면 JS 로 보내 채점하지 않는다.** "틀린 문항을 알려 주면 친절할 텐데" 는 R7 위반이다.
- 권한 검사를 화면에서만 하지 않는다 — 신입이 다른 사람 이름으로 API 를 불러도 403 이어야 한다.
- `tests/` 와 `seed/` 의 칸 이름 · 파일 이름, `data-testid` 이름, 거부 코드(400 · 403 · 404 · 409)를 바꾸지 않는다.

## 완료 보고 형식

마지막 답은 아래 형식으로만 한다. **PRD 에 없는 API · 칸 · 화면 요소를 하나라도 추가했으면 'PRD 와 다르게 한 것' 에 전부 적는다.**

```
DoD: 9/9 (또는 n/9, 실패한 T번호와 이유)
만든 파일: main.py, static/index.html, seed/*.csv
범위 밖 기능: 없음 (있으면 이름)
PRD 와 다르게 한 것: 없음 (있으면 무엇과 이유 — 추가한 API 경로 포함)
```
