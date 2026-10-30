# CLAUDE.md — 가나다식품 「주문 · 재고 백오피스」
요구사항은 `PRD.md`, 이 파일은 만드는 방법과 끝났다고 말할 조건이다.
- 스택은 바꾸지 않는다: Python 3 · FastAPI · uvicorn · `sqlite3` · 순수 HTML/JS/CSS. 외부 패키지는 `fastapi` · `uvicorn` 만, CDN · 빌드 도구 · 프런트 프레임워크 금지.
- 화면은 `static/index.html` 에 둔다(JS 는 그 안이나 `static/app.js`).
- 서버는 시작할 때마다 `seed/*.csv` 를 읽어 `backoffice.db` 를 새로 만든다.
- `python -m pytest tests -q` 가 9/9 여야 끝난 것이다. 돌려 보지 않았거나 통과하지 못했으면 끝났다고 말하지 않는다.
- `tests/test_dod.py` 는 읽기만 한다. 고치거나 지우거나 건너뛰지 않는다. 테스트가 실패하면 앱을 고친다.
- `seed/` 의 파일 · 칸 이름, `data-testid` 이름, 거부 코드(400 · 403 · 404 · 409)를 바꾸지 않는다.
- PRD 8 범위 밖 기능은 넣지 않는다. "있으면 좋을" 것도 넣지 않는다.
마지막 답은 아래 다섯 줄로만 한다. PRD 에 없는 API · 칸 · 화면 요소를 추가했으면 넷째 줄에 전부 적는다.
DoD: 9/9 (또는 n/9, 실패한 T번호와 이유)
만든 파일: main.py, static/index.html, seed/*.csv
범위 밖 기능: 없음 (있으면 이름)
PRD 와 다르게 한 것: 없음 (있으면 무엇과 이유 — 추가한 API 경로 포함)
PRD 가 정하지 않아 직접 정한 것: 없음 (있으면 무엇을 어떻게)
