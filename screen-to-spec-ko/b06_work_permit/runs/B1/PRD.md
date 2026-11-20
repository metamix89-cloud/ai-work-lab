# PRD — 뚝딱건설 해뜰현장 「위험 작업 허가서」

> 「이 화면, PRD 로는 이렇게」 2부 6편(건설 · 시설 관리). 회사 · 현장 · 작업자 · 허가 건은 모두 교육용 가상 데이터(뚝딱건설은 가상 회사).
> 아래 규칙은 전부 **이 현장의 규칙**이다. 실제 법규 · 법정 서식 · 고시의 수치가 아니다.
> 형식은 10칸(개요 · 사용자 · 기능 · 화면 · 데이터 · 업무 규칙 · 제약 · 범위 밖 · 개발 단계 · 완료 기준).

## 1. 개요

- **배경:** 해뜰현장은 고소 · 화기 · 밀폐 작업을 종이 허가서로 돌린다. 아침에 받은 허가로 저녁까지 일하고, 신청한 반장이 자기 허가에 도장을 찍고, 지하 기계실에서 용접(화기)과 도장(밀폐) 작업이 같은 시간에 붙어 있었다.
- **목적:** 허가서를 화면에서 신청 → 안전 담당 검토 → 현장 책임자 승인 → 작업 시작 → 종료로 돌리고, **허가에는 끝 시각이 있고(승인 뒤 8시간 · 당일), 신청자는 자기 허가를 승인하지 못하며, 같은 구역 · 같은 시간의 상충 작업은 승인되지 않게** 서버가 지킨다.
- **성공 기준:** 만료된 허가로 작업 시작 0건. 본인 승인 0건. 상충 작업 동시 승인 0건.

## 2. 사용자

- **작업자(반장) · 안전 담당 · 현장 책임자 3유형.** 로그인 없이 화면 위 **사용자 선택 상자**에서 고른다. API 는 요청자를 본문의 `user` 또는 쿼리의 `viewer`(user_id)로 받는다. **로그인은 8 범위 밖.**
- 작업자: 허가 신청, **자기 허가**의 상태 조회, 작업 시작 · 종료.
- 안전 담당: 모든 허가 조회, 검토(필수 점검 항목이 다 체크된 신청을 '검토 완료' 로), 현황판 보기.
- 현장 책임자: 모든 허가 조회, 승인, 현황판(오늘 · 구역별 · 시간대별) 보기. 현장 책임자도 허가를 **신청할 수는 있다**(직접 작업반을 끌 때) — 단 자기 신청은 승인하지 못한다.

## 3. 기능 요구사항

| 번호 | 기능 | MoSCoW | Phase |
|---|---|---|---|
| F1 | 허가 신청: 작업 종류(고소 · 화기 · 밀폐) · 구역 · 작업 시간(시작 · 종료) · 그 종류의 필수 점검 항목 체크 | Must | 1 |
| F2 | 검토(안전 담당) → 승인(현장 책임자) → 작업 시작(신청자) → 종료(신청자 또는 승인자) | Must | 1 |
| F3 | 허가 유효 시간: 승인 시각부터 8시간, 그날 23:59 를 넘지 않는다. 지나면 '만료' — 서버 시계로 판정 | Must | 1 |
| F4 | 상충 검사: 같은 구역 · 겹치는 시간에 화기 + 밀폐는 함께 승인되지 않는다 | Must | 1 |
| F5 | 현황판: 오늘 · 구역별 · 시간대별 허가 격자, 상충 경고 | Must | 1 |
| F6 | API: `GET /api/users` · `GET /api/work-types` · `GET /api/zones` · `GET /api/permits?viewer=` · `GET /api/permits/{permit_id}?viewer=` · `POST /api/permits` · `POST /api/permits/{permit_id}/review` · `POST /api/permits/{permit_id}/approve` · `POST /api/permits/{permit_id}/start` · `POST /api/permits/{permit_id}/close` · `GET /api/dashboard?viewer=` | Must | 1 |

## 4. 화면

한 페이지(`/`). 위 사용자 선택, 왼쪽 허가 목록, 오른쪽 선택한 허가의 상세와 단추. 안전 담당 · 현장 책임자에게는 아래에 현황판 격자.

- **사용자 선택:** `data-testid="user"` (`<select>`, option 의 value 는 user_id, 출처 `GET /api/users`). 처음엔 첫 번째 사용자.
- **허가 줄:** `data-testid="permit"` + `data-id`(permit_id) + `data-status`(아래 5 의 상태값). 안에 허가 번호 · 작업 종류 · 구역 · 시간. 누르면 오른쪽에 상세(출처 `GET /api/permits/{id}`).
- **상세의 단추 — 역할과 상태에 맞는 것만 둔다(요소 자체를 넣지 않는다):**
  - 안전 담당 + `requested` → 검토 `data-testid="review"`
  - 현장 책임자 + `reviewed` → 승인 `data-testid="approve"`
  - 신청자 본인 + `approved` → 작업 시작 `data-testid="start"`
  - 신청자 또는 승인자 + `started` → 종료 `data-testid="close"`
- **신청 폼(모든 사용자):** 작업 종류 `data-testid="work-type"`(`<select>`, 출처 `GET /api/work-types`) 를 고르면 그 종류의 필수 점검 항목이 체크박스 `data-testid="check-item"` + `data-id`(item_id) 로 바뀐다 · 구역 `data-testid="zone"`(`<select>`) · 시작 `data-testid="start-at"` · 종료 `data-testid="end-at"` · 신청 `data-testid="submit"`.
- **현황판(안전 담당 · 현장 책임자):** `data-testid="grid"` — 행은 구역, 열은 06시~18시. 칸 `data-testid="cell"` + `data-zone` + `data-hour`, 그 시간에 걸친 허가를 작업 종류 색으로. 상충 쌍이 있으면 `data-testid="conflict"` 경고 줄(허가 번호 둘). 출처 `GET /api/dashboard`. 작업자에게는 격자가 **없다.**
- **메시지 줄:** `data-testid="message"` — 서버가 거부하면 `detail` 그대로.
- **오류 상태:** API 가 실패하면 `불러오지 못했습니다` 와 다시 시도 버튼.
- 문구를 테스트하는 요소는 그 문구가 **손잡이 요소 안에** 있어야 한다.

## 5. 데이터

- **원본:** 프로젝트 루트 `seed/` CSV 4개. 서버는 **시작할 때마다** CSV 를 읽어 SQLite(`permit.db`)를 **새로** 만든다. 신청 · 검토 · 승인 · 시작 · 종료는 DB 에 쓴다(서버가 도는 동안 유지).

| 파일 | 칸 | 형식과 예시 |
|---|---|---|
| `seed/users.csv` | `user_id, name, role` | `w1` · `김작업` · `role` 은 `worker`(작업자 · 반장) · `safety`(안전 담당) · `manager`(현장 책임자) 중 하나 |
| `seed/zones.csv` | `zone_id, name` | `Z1` · `본관 3층` |
| `seed/check_items.csv` | `work_type, item_id, name` | `hot` · `F1` · `소화기 비치`. `work_type` 은 `height`(고소) · `hot`(화기) · `confined`(밀폐) 셋뿐. 종류마다 항목 3개 |
| `seed/permits.csv` | `permit_id, work_type, zone_id, requester_id, start_at, end_at, status, checked, reviewed_by, approved_by, approved_at, started_at, closed_at` | `WP-0101` · `hot` · `Z2` · `w1` · 시각은 `YYYY-MM-DD HH:MM` · `status` 는 `requested` · `reviewed` · `approved` · `started` · `closed` 중 하나 · `checked` 는 체크한 item_id 를 `\|` 로 이음(`F1\|F2\|F3`) · 아직 없는 칸은 빈칸 |

- **허가 번호:** `WP-` + 네 자리 숫자. 새 허가는 **지금까지의 최댓값 + 1**(`WP-0109` 다음은 `WP-0110`).
- **상태:** `requested`(신청) → `reviewed`(검토 완료) → `approved`(승인) → `started`(작업 중) → `closed`(종료). 응답의 `status` 에는 한 가지가 더 있다 — **`expired`(만료)**: `approved` 또는 `started` 인데 지금(서버 시계)이 `valid_until` 을 지났으면 응답에서는 `expired` 로 보인다. DB 에 따로 쓰지 않아도 된다(응답에서 계산).
- **유효 시각 `valid_until`:** 승인 때 서버가 만든다 = `approved_at + 8시간`, 단 `approved_at` 과 **같은 날 23:59 를 넘지 않는다.** 08:30 승인 → 16:30 · 20:00 승인 → 23:59.
- **테이블:** 접두어 `wp_` — `wp_users` · `wp_zones` · `wp_check_items` · `wp_permits`.
- **가상 데이터:** 작업자 2명 · 안전 담당 1명 · 현장 책임자 2명, 구역 3개, 허가 8건 이상(신청 · 검토 완료 · 승인 · 작업 중 · 종료 · **만료된 것**을 섞어서). **같은 CSV 를 다른 내용으로 바꿔 끼울 수 있어야** 한다.
- **시각:** '지금' 은 **서버 로컬 시각**이다. 승인 · 시작 · 종료 시각은 서버가 적는다(본문으로 받지 않는다). 만료 판정도 서버 시계.
- **API**
  - `GET /api/users` → `[{"user_id","name","role"}]`
  - `GET /api/work-types` → `[{"work_type","name","items":[{"item_id","name"}]}]` (`name` 은 고소 작업 · 화기 작업 · 밀폐 작업)
  - `GET /api/zones` → `[{"zone_id","name"}]`
  - `GET /api/permits?viewer=w1` → `[{"permit_id","work_type","work_type_name","zone_id","zone_name","requester_id","requester_name","start_at","end_at","status","checked":[item_id…],"reviewed_by","approved_by","approved_at","valid_until","started_at","closed_at"}]` — 작업자면 **자기 것만**, 안전 담당 · 현장 책임자면 전부. `start_at` 순, 같으면 permit_id 순. 없는 칸은 `null`.
  - `GET /api/permits/{permit_id}?viewer=w1` → 위 한 건
  - `POST /api/permits` 본문 `{"user":"w1","work_type":"hot","zone_id":"Z2","start_at":"2026-11-06 13:00","end_at":"2026-11-06 15:00","checked":["F1","F2","F3"]}` → 201 위 한 건(`status` `requested`)
  - `POST /api/permits/{permit_id}/review` 본문 `{"user":"s1"}` → 200 `{"permit_id","status":"reviewed","reviewed_by"}`
  - `POST /api/permits/{permit_id}/approve` 본문 `{"user":"m1"}` → 200 `{"permit_id","status":"approved","approved_by","approved_at","valid_until"}`
  - `POST /api/permits/{permit_id}/start` 본문 `{"user":"w1"}` → 200 `{"permit_id","status":"started","started_at"}`
  - `POST /api/permits/{permit_id}/close` 본문 `{"user":"w1"}` → 200 `{"permit_id","status":"closed","closed_at"}`
  - `GET /api/dashboard?viewer=m1` → `{"date":"YYYY-MM-DD","hours":[6,7,…,18],"zones":[{"zone_id","name","permits":[{"permit_id","work_type","status","start_at","end_at","requester_name"}]}],"conflicts":[{"zone_id","permit_ids":[두 개]}]}` — **오늘**(서버 날짜)에 걸친 허가 중 `closed` 가 아닌 것. `conflicts` 는 6 의 R6 기준으로 맞물리는 쌍(한쪽이 승인 · 작업 중이고 유효, 다른 쪽이 종료 아닌 모든 상태).
  - 거부 응답은 모두 `{"detail": "사유"}`.

## 6. 업무 규칙

| 번호 | 규칙 |
|---|---|
| R1 | **작업 종류별 필수 점검 항목.** 작업 종류는 `height` · `hot` · `confined` 셋뿐 — 아니면 400 `작업 종류를 확인하세요`. 신청의 `checked` 에 그 종류의 항목 3개가 **모두** 있어야 한다 — 하나라도 비면 400 `필수 점검 항목이 비었습니다 (항목 이름)`. 그 종류에 없는 item_id 가 섞여 있으면 400 `점검 항목을 확인하세요`. |
| R2 | **작업 시간.** `start_at` · `end_at` 은 `YYYY-MM-DD HH:MM` — 아니면 400 `시각 형식은 YYYY-MM-DD HH:MM 입니다`. `end_at` 은 `start_at` 보다 뒤 — 아니면 400 `종료 시각이 시작 시각보다 앞입니다`. 시작 시각이 이미 지났어도 받는다(현장에서 늦게 올리는 일이 있다). |
| R3 | **누가 무엇을.** 신청은 누구나. 검토는 안전 담당만 — 아니면 403 `안전 담당만 검토할 수 있습니다`. 승인은 현장 책임자만 — 아니면 403 `현장 책임자만 승인할 수 있습니다`. **신청자는 자기 허가를 승인할 수 없다**(현장 책임자여도) — 403 `자기 허가는 승인할 수 없습니다`. 작업 시작은 **신청자만** — 아니면 403 `신청자만 작업을 시작할 수 있습니다`. 종료는 **신청자 또는 승인자** — 아니면 403 `신청자 또는 승인자만 종료할 수 있습니다`. 작업자는 자기 허가만 본다 — 남의 건 `GET /api/permits/{id}` 는 403 `본인 허가만 볼 수 있습니다`, 목록은 자기 것만. 현황판은 안전 담당 · 현장 책임자만 — 작업자는 403 `현황판은 안전 담당과 현장 책임자만 볼 수 있습니다`. |
| R4 | **순서(상태 기계).** 검토는 `requested` 에서만 — 아니면 409 `검토할 상태가 아닙니다`. 승인은 `reviewed` 에서만 — `requested` 면 409 `검토 전에는 승인할 수 없습니다`, 그 밖은 409 `승인할 상태가 아닙니다`. 작업 시작은 `approved` 에서만 — `requested` · `reviewed` 면 409 `승인 전에는 작업을 시작할 수 없습니다`, `started` 면 409 `이미 시작한 작업입니다`, `closed` 면 409 `종료된 허가입니다`. 종료는 `started` 에서만 — 아니면 409 `시작한 작업만 종료할 수 있습니다`. 역행 · 건너뛰기 없음. |
| R5 | **유효 시간 · 만료.** `valid_until` = 승인 시각 + 8시간, 같은 날 23:59 를 넘지 않는다(5 데이터). 지금이 `valid_until` 을 **지났으면**(`지금 > valid_until`) 만료: 응답 `status` 는 `expired`, 작업 시작은 409 `허가가 만료되었습니다`. `valid_until` 과 같은 분까지는 유효. **연장은 없다 — 새 허가를 신청한다.** 작업 중(`started`)인 허가가 만료되어도 종료(`close`)는 된다(기록을 닫는다). |
| R6 | **상충 작업.** 승인하려는 허가와 **같은 구역**에, **승인 · 작업 중이고 유효한**(만료 아님) 다른 허가가 있고, 작업 시간이 **겹치고**(`start_at < 상대.end_at` 이고 `상대.start_at < end_at`), 두 작업 종류가 **화기와 밀폐의 짝**이면 승인은 409 `같은 구역에 상충 작업이 있습니다 (상대 허가 번호)`. 화기 + 화기, 밀폐 + 밀폐, 고소 + 무엇이든은 상충이 아니다. 끝 시각과 시작 시각이 같으면 겹치지 않는다. 신청 · 검토 단계에서는 막지 않는다(승인 때만). |
| R7 | **현황판.** 오늘(서버 날짜)에 걸친 허가(`start_at < 내일 00:00` 이고 `end_at > 오늘 00:00`) 중 `closed` 가 아닌 것을 구역별로. `conflicts` 는 R6 의 기준(같은 구역 · 겹침 · 화기와 밀폐)에 맞는 쌍 중 **한쪽이 승인 · 작업 중이고 유효**하고 다른 쪽이 종료가 아닌 것 — 아직 승인 전인 신청도 경고에 든다(승인하면 막힐 것이라는 뜻). |
| R8 | **입력과 거부 순서.** `user`(또는 `viewer`)가 문자열로 없으면 400 `사용자를 확인하세요`. 거부가 둘 이상이면 **'무엇을 찾아야 알 수 있나'** 순서로 하나만: 본문만 보면 아는 것(400: 사용자 없음 · 작업 종류 · 시각 형식 · 종료가 앞) → 없는 사용자 · 허가 · 구역(404) → 사용자 · 허가를 찾아야 아는 권한(403) → 점검 항목표를 찾아야 아는 400(항목 비었음 · 모르는 항목) → 상태(409: 순서 → 만료 → 상충). |

## 7. 제약

- 스택: **Python FastAPI + 순수 HTML/JS(프레임워크 · 빌드 도구 없음) + SQLite.**
- 실행: 프로젝트 루트에서 `python -m uvicorn main:app --port 8000` (`main.py` 에 `app = FastAPI()`). 포트는 환경 변수 `PORT` 가 있으면 그것. **`main.py` 안에서 다른 파일을 import 하거나 파일을 열면 프로젝트 루트 기준 절대 경로로**(테스트는 다른 폴더에서 서버를 띄운다).
- '지금' 은 서버 로컬 시각. 시각 문자열은 `YYYY-MM-DD HH:MM`. 외부 네트워크 · CDN 없음. 외부 패키지는 `fastapi` · `uvicorn` 만. 한글 UI.

## 8. 범위 밖 (Won't)

- 로그인 · 회원가입, 반려 · 재신청(검토 · 승인은 통과만 있다), 허가 연장(새 허가로), 사진 · 서류 첨부, 문자 · 알림, 전자 서명, 가스 측정값 입력, 작업자 명단 · 출역, 자재 반입, 안전 점검표 · 하자 접수, 통계 · 보고서, **점검 항목 · 구역 · 사용자 편집 화면(데이터 편집 화면)**, 다크 모드.

## 9. 개발 단계

1. **Phase 1:** `seed/` → SQLite, API 11개와 규칙 R1~R8, `/` 화면(사용자 · 허가 목록 · 상세와 단추 · 신청 폼 · 현황판 격자 · 메시지 · 오류).
2. 그 외 없음.

## 10. 완료 기준 (DoD)

`tests/test_dod.py` 가 완료 기준이다. 아래 9개가 모두 통과해야 끝난다.

- [ ] T1 `/` 가 200 으로 열리고 '허가' 가 보인다.
- [ ] T2 사용자 5명 · 작업 종류 3개(항목 3개씩) · 구역 3개 · 허가 목록(작업자는 자기 것만, 책임자는 전부, `start_at` 순) · 한 건 조회 · 현황판(구역 3개 · 오늘 허가 · 상충 쌍 하나)이 계약대로.
- [ ] T3 신청: 항목 하나 빠지면 400 · 작업 종류 오타 400 · 종료가 앞이면 400 · 없는 구역 404 · 다 갖추면 201 · 번호는 `WP-` + 최댓값 + 1 · 상태 `requested` (R1 · R2).
- [ ] T4 순서 · 역할: 작업자의 검토 403 · 안전 담당 검토 200 · 두 번째 검토 409 · 작업자의 승인 403 · 책임자 승인 200(`valid_until` = 승인 + 8시간, 당일 23:59 상한) · 검토 전 승인 409 · **신청자 본인(책임자)의 승인 403** (R3 · R4).
- [ ] T5 작업 시작 · 만료: 승인 전 시작 409 · 남이 시작 403 · 신청자 시작 200 · 두 번째 시작 409 · **만료된 허가(승인 9시간 전)는 응답 `expired` · 시작 409** (R3 · R4 · R5).
- [ ] T6 상충: 같은 구역 · 겹치는 시간의 화기를 밀폐 위에 승인하면 409 · 다른 구역은 200 · 같은 구역이라도 시간이 안 겹치면 200 (R6).
- [ ] T7 종료: 제3자 종료 403 · 승인자 종료 200 · 신청자 종료 200 · 종료 뒤 시작 409 · 두 번째 종료 409 · 승인만 된 건 종료 409 (R3 · R4).
- [ ] T8 거부 순서 · 권한: 사용자 없음 400 · 없는 허가 404(권한 전에) · 권한 403(상태 전에) · 남의 허가 시작은 만료보다 403 먼저 · 작업 종류 오타 + 없는 구역은 400 먼저 · 없는 구역 + 항목 누락은 404 먼저 · 작업자의 현황판 403 · 작업자가 남의 건 조회 403 (R8).
- [ ] T9 화면: 책임자로 열면 현황판 격자(칸 · 상충 경고)가 있고, 작업자로 승인된 자기 허가를 누르면 작업 시작 단추가 있고 누르면 작업 중이 된다. 안전 담당으로 신청 건을 누르면 검토 단추는 있고 승인 단추는 없다. 작업자에게는 격자가 없다.
