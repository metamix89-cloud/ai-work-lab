# PRD — 콩알반도체 「불량 신고 · 조치 추적판」

> 「이 화면, PRD 로는 이렇게」 2부 1편(제조 · 전자 부품). 회사 · 직원 · 로트 · 불량은 모두 교육용 가상 데이터(콩알반도체는 가상 회사).
> 형식은 10칸(개요 · 사용자 · 기능 · 화면 · 데이터 · 업무 규칙 · 제약 · 범위 밖 · 개발 단계 · 완료 기준).

## 1. 개요

- **배경:** 콩알반도체 조립 라인에서 불량이 나오면 작업자가 메신저에 올리고 품질팀이 엑셀에 옮겨 적는다. 누가 조치 중인지, 기한이 언제인지 모르고, 조치한 사람이 자기 조치를 "확인 완료" 로 닫는 일이 있었다.
- **목적:** 작업자가 **로트 단위로 불량을 신고**하면, 품질팀이 **원인 · 담당자를 정해 조치하고, 다른 사람이 검증한 뒤** 종결한다. 심각도에 따라 **기한**이 자동으로 붙고, 넘긴 건은 바로 보인다.
- **성공 기준:** 자기 조치를 자기가 검증한 건 0건. 기한 넘김을 모르고 지나간 건 0건.

## 2. 사용자

- **작업자 · 품질팀 2유형.** 로그인 없이 화면 위 **사용자 선택 상자**에서 고른다. API 는 요청자를 본문의 `user`(user_id)로 받는다. **로그인은 8 범위 밖.**
- 작업자: 신고. 품질팀: 신고 · 원인 분석(담당 배정) · 조치 등록 · 검증.

## 3. 기능 요구사항

| 번호 | 기능 | MoSCoW | Phase |
|---|---|---|---|
| F1 | 불량 신고: 로트 · 증상 · 심각도 · 수량 | Must | 1 |
| F2 | 추적판: 신고마다 로트 · 제품 · 라인 · 증상 · 심각도 · 수량 · 상태 · 담당 · 기한 · 넘김 여부 · 재작업 횟수 | Must | 1 |
| F3 | 동작: 원인 분석(원인 · 담당) · 조치 등록 · 검증(통과 · 실패) | Must | 1 |
| F4 | 요약: 미종결 수 · 기한 넘김 수 · 재작업 횟수 합 | Must | 1 |
| F5 | API: `GET /api/users` · `GET /api/lots` · `GET /api/symptoms` · `GET /api/causes` · `GET /api/defects` · `POST /api/defects` · `POST /api/defects/{defect_id}/{action}` (`action` = `analyze` · `fix` · `verify`) | Must | 1 |

## 4. 화면

한 페이지(`/`). 위 사용자 선택과 신고 폼, 가운데 요약 3칸, 아래 추적판 표.

- **사용자 선택:** `data-testid="user"` (`<select>`, option 의 value 는 user_id). 처음엔 첫 번째 사용자.
- **신고 폼:** 로트 `data-testid="lot"`(`<select>`) · 증상 `data-testid="symptom"`(`<select>`) · 심각도 `data-testid="severity"`(`<select>`, 치명 · 중 · 경) · 수량 `data-testid="qty"` · 신고 `data-testid="report"`.
- **요약:** `data-testid="sum-open"` · `sum-overdue` · `sum-rework` — 안에 숫자.
- **추적판 줄:** `data-testid="defect"` + `data-id`(defect_id) + `data-status`(reported · fixing · verifying · closed) + `data-overdue="1|0"`. 안에 상태를 한글로(신고 · 조치 중 · 검증 대기 · 종결). **그 사용자가 그 상태에서 할 수 있는 동작만** 버튼으로: 원인 분석 `data-testid="act-analyze"`, 조치 등록 `data-testid="act-fix"`, 검증 통과 `data-testid="act-pass"` · 실패 `data-testid="act-fail"` — 안내일 뿐, 막는 건 서버.
- **원인 분석 입력:** 원인 `data-testid="cause"`(`<select>`) · 담당자 `data-testid="assignee"`(`<select>`, 품질팀만). **조치 등록 입력:** 조치 내용 `data-testid="note"`.
- **메시지 줄:** `data-testid="message"` — 서버가 거부하면 `detail` 그대로.
- **오류 상태:** API 가 실패하면 `불러오지 못했습니다` 와 다시 시도 버튼.
- 문구를 테스트하는 요소는 그 문구가 **손잡이 요소 안에** 있어야 한다.

## 5. 데이터

- **원본:** 프로젝트 루트 `seed/` CSV 5개. 서버는 **시작할 때마다** CSV 를 읽어 SQLite(`qc.db`)를 **새로** 만든다. 신고 · 동작 결과는 DB 에 쓴다(서버가 도는 동안 유지).

| 파일 | 칸 | 형식과 예시 |
|---|---|---|
| `seed/users.csv` | `user_id, name, role` | `user_id` 문자열 `w1` · `role` `worker`(작업자) 또는 `quality`(품질팀) |
| `seed/lots.csv` | `lot_id, product, line, qty` | `lot_id` 문자열 `L-1001` · `product` `콩알칩 A` · `line` `1라인` · `qty` 로트 수량 1 이상 정수 |
| `seed/symptoms.csv` | `code, label` | `code` 문자열 `S01` · `label` `외관 스크래치` |
| `seed/causes.csv` | `code, label` | `code` 문자열 `C01` · `label` `장비` |
| `seed/defects.csv` | `defect_id, lot_id, symptom, severity, qty, status, reporter, assignee, cause, reported_at, rework` | `defect_id` 문자열 `F001` · `severity` `치명` · `중` · `경` · `status` `reported` · `fixing` · `verifying` · `closed` · `assignee` · `cause` 빈칸 가능 · `reported_at` `2026-10-24 09:10` · `rework` 0 이상 정수 |

- 새 신고의 `defect_id` 는 서버가 정한다(기존 id 와 겹치지 않게). `reported_at` 은 서버의 지금.
- **테이블:** 접두어 `qc_` — `qc_users` · `qc_lots` · `qc_symptoms` · `qc_causes` · `qc_defects` · `qc_history(defect_id, at, by, action, note)`.
- **가상 데이터:** 사용자 5명(작업자 2 · 품질팀 3), 로트 4개, 증상 4개, 원인 5개(그중 하나는 `미상`), 불량 6건 이상(상태 네 가지 다 있게, 기한 넘긴 것 1건 이상). **같은 CSV 를 다른 내용으로 바꿔 끼울 수 있어야** 한다.
- **API**
  - `GET /api/users` → `[{"user_id","name","role"}]`
  - `GET /api/lots` → `[{"lot_id","product","line","qty"}]`
  - `GET /api/symptoms` · `GET /api/causes` → `[{"code","label"}]`
  - `GET /api/defects` → `{"defects":[{"defect_id","lot_id","product","line","symptom","severity","qty","status","reporter","assignee"(또는 null),"cause"(또는 null),"reported_at","due"(YYYY-MM-DD),"overdue"(true|false),"rework"}], "summary":{"open","overdue","rework"}}` 신고 시각 오래된 순
  - `POST /api/defects` 본문 `{"user":"w1","lot_id":"L-1001","symptom":"S01","severity":"중","qty":5}` → 201 불량 하나(위 모양)
  - `POST /api/defects/{defect_id}/analyze` 본문 `{"user":"q1","cause":"C01","assignee":"q2"}` → 200 불량 하나
  - `POST /api/defects/{defect_id}/fix` 본문 `{"user":"q2","note":"..."}` → 200 불량 하나
  - `POST /api/defects/{defect_id}/verify` 본문 `{"user":"q3","result":"pass"|"fail"}` → 200 불량 하나
  - 거부 응답은 모두 `{"detail": "사유"}`.

## 6. 업무 규칙

| 번호 | 규칙 |
|---|---|
| R1 | **상태와 동작.** 신고 `reported` —원인 분석 `analyze`→ 조치 중 `fixing` —조치 등록 `fix`→ 검증 대기 `verifying` —검증 `verify`→ 통과면 종결 `closed`, **실패면 조치 중 `fixing` 으로 돌아가고 `rework` 가 1 는다.** 그 밖의 상태에서 그 동작은 409 `지금 상태에서는 할 수 없습니다`. 종결은 잠금 — 어떤 동작이든 409 `종결된 건입니다`. |
| R2 | **신고 입력.** `lot_id` 는 로트 목록에 있어야(없으면 404 `로트를 확인하세요`), `symptom` 은 증상 목록 · `severity` 는 세 값 중 하나(아니면 400 `입력을 확인하세요`), `qty` 는 1 이상 정수이고 **로트 수량을 넘지 않는다**(아니면 400 `수량을 확인하세요`). |
| R3 | **같은 로트 · 같은 증상의 미종결 신고가 있으면** 새 신고는 409 `이미 신고된 불량입니다`(종결된 건은 상관없다). |
| R4 | **기한** = 신고 날짜 + 치명 1일 · 중 3일 · 경 7일 (`due`). **넘김** = 종결이 아니고 오늘(서버 로컬 날짜) > `due`. **기한 당일은 넘김이 아니다.** 종결된 건은 기한이 지났어도 넘김이 아니다. |
| R5 | **원인 분석.** 품질팀만(작업자는 403 `품질팀만 할 수 있습니다`). `cause` 는 원인 목록에, `assignee` 는 **품질팀** 사용자여야(아니면 400 `원인과 담당자를 확인하세요`). |
| R6 | **조치 등록.** **담당자(`assignee`)만** — 다른 사람은 403 `담당자만 조치를 등록할 수 있습니다`. `note` 는 앞뒤 공백을 뺀 길이 1~500자(아니면 400 `조치 내용을 입력하세요`). |
| R7 | **검증은 제3자.** 품질팀이면서 **신고자도 담당자도 아닌 사람**만 — 담당자면 403 `본인 조치는 검증할 수 없습니다`, 신고자면 403 `신고자는 검증할 수 없습니다`, 작업자면 403 `품질팀만 할 수 있습니다`. `result` 는 `pass` · `fail` 중 하나(아니면 400 `입력을 확인하세요`). |
| R8 | **요약.** `open` = 종결이 아닌 건수 · `overdue` = R4 넘김 건수 · `rework` = 모든 건의 `rework` 합(종결 포함). |
| R9 | **입력과 거부 순서.** `user` 가 문자열로 없으면 400 `사용자를 확인하세요`. 거부가 둘 이상이면 **'무엇을 찾아야 알 수 있나'** 순서로 하나만: 본문만 보면 아는 것(400) → 없는 건 · 사용자 · 로트(404) → 사용자 · 건을 찾아야 아는 권한(403) → 상태 · 중복을 봐야 아는 것(409). |

## 7. 제약

- 스택: **Python FastAPI + 순수 HTML/JS(프레임워크 · 빌드 도구 없음) + SQLite.** 수량은 정수.
- 실행: 프로젝트 루트에서 `python -m uvicorn main:app --port 8000` (`main.py` 에 `app = FastAPI()`). 포트는 환경 변수 `PORT` 가 있으면 그것.
- '오늘' 은 서버 로컬 날짜. 외부 네트워크 · CDN 없음. 외부 패키지는 `fastapi` · `uvicorn` 만. 한글 UI.

## 8. 범위 밖 (Won't)

- 로그인 · 회원, 사진 첨부, 설비 점검 일지 · 자재 입출고 · 인수인계(앱 지도의 다른 앱), 불량률 통계 · 차트, 알림 · 메일, 신고 수정 · 삭제, **로트 · 사용자 · 원인 편집 화면(데이터 편집 화면)**, 엑셀 내려받기, 다크 모드.

## 9. 개발 단계

1. **Phase 1:** `seed/` → SQLite, API 5개와 규칙 R1~R9, `/` 화면(사용자 · 신고 폼 · 요약 · 추적판 · 메시지 · 오류).
2. 그 외 없음.

## 10. 완료 기준 (DoD)

`tests/test_dod.py` 가 완료 기준이다. 아래 9개가 모두 통과해야 끝난다.

- [ ] T1 `/` 가 200 으로 열리고 '불량' 이 보인다.
- [ ] T2 사용자 5명(역할) · 로트 4개 · 불량 목록이 계약대로(오래된 순, 네 상태) · 요약 (고정 데이터에서 open 5 · overdue 1 · rework 1).
- [ ] T3 신고: 수량 0 · 로트 수량 초과는 400, 없는 로트는 404, 없는 증상은 400, 같은 로트 · 증상의 미종결 건이 있으면 409, 종결된 건과 같은 로트 · 증상은 201 이고 치명이면 기한이 내일 (R2 · R3 · R4).
- [ ] T4 원인 분석: 작업자는 403, 없는 원인 · 작업자를 담당으로는 400, 품질팀 + 올바른 입력은 200 이고 조치 중 (R5).
- [ ] T5 조치 등록: 담당자가 아닌 품질팀은 403, 빈 내용은 400, 검증 대기 건에 담당자가 다시 등록하면 409, 조치 중 건의 담당자는 200 이고 검증 대기 (R1 · R6).
- [ ] T6 검증: 담당자 본인은 403, 신고자는 403, 제3자의 실패는 조치 중으로 돌아가고 rework 1, 다시 조치 뒤 제3자의 통과는 종결 (R1 · R7).
- [ ] T7 기한: 중 · 4일 전 신고는 넘김, 경 · 7일 전 신고(기한 당일)는 넘김 아님, 기한 지난 종결 건은 넘김 아님, 요약 overdue 1 (R4 · R8).
- [ ] T8 거부 순서: 본문 없음 + 없는 건은 400, 없는 건은 404, 없는 사용자는 404, 작업자가 종결 건을 검증하면 403(409 아님), 품질팀이 종결 건을 검증하면 409 (R1 · R9).
- [ ] T9 화면: 작업자에게는 원인 분석 버튼이 없고, 품질팀으로 바꾸면 신고 상태 줄에 원인 분석 버튼이 있다. 담당자 본인에게는 자기 건의 검증 버튼이 없다. 요약 숫자가 보이고, 넘긴 줄은 `data-overdue="1"`. 수량 0 으로 신고하면 메시지 줄에 `수량을 확인하세요`.
