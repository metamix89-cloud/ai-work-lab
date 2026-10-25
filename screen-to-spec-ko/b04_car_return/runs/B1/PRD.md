# PRD — 부릉부릉렌터카 「반납 점검표 · 추가 요금」

> 「이 화면, PRD 로는 이렇게」 2부 4편(렌터카 · 차량). 회사 · 고객 · 차량 · 대여 건은 모두 교육용 가상 데이터(부릉부릉렌터카는 가상 회사).
> 형식은 10칸(개요 · 사용자 · 기능 · 화면 · 데이터 · 업무 규칙 · 제약 · 범위 밖 · 개발 단계 · 완료 기준).

## 1. 개요

- **배경:** 부릉부릉렌터카는 차를 돌려받을 때 직원이 종이 점검표에 연료 · 주행거리 · 흠집을 적고 추가 요금을 머리로 계산한다. 직원마다 지연 요금을 다르게 받았고, 대여 전부터 있던 흠집을 고객에게 청구해 다툼이 났고, 사진 없는 흠집은 나중에 증명을 못 했다.
- **목적:** 반납 점검표를 화면에서 적으면 **지연 · 연료 · 손상 추가 요금을 서버가 회사 기준대로 계산**하고, **대여 전부터 있던 손상은 청구하지 않으며**, **사진 없는 손상은 받지 않는다.**
- **성공 기준:** 직원마다 다른 지연 요금 0건. 기존 손상 청구 다툼 0건. 사진 없는 손상 청구 0건.

## 2. 사용자

- **고객 · 직원 2유형.** 로그인 없이 화면 위 **사용자 선택 상자**에서 고른다. API 는 요청자를 본문의 `user` 또는 쿼리의 `viewer`(user_id)로 받는다. **로그인은 8 범위 밖.**
- 고객: 자기 대여 건과 청구 내역 조회만. 직원: 모든 대여 건 조회, 반납 점검(요금 미리보기 · 반납 처리).

## 3. 기능 요구사항

| 번호 | 기능 | MoSCoW | Phase |
|---|---|---|---|
| F1 | 대여 목록: 차량 · 고객 · 반납 예정 시각 · 상태(대여 중 · 반납 완료) · 대여 때 연료 칸 · 주행거리 | Must | 1 |
| F2 | 반납 점검표: 반납 시각 · 연료 칸(0~8) · 주행거리 · 손상 항목(부위 · 등급 · 사진 수) 여러 개 · 대여 전 손상 표시 | Must | 1 |
| F3 | 요금 미리보기: 지연 · 연료 · 손상 · 합계를 서버가 계산해 보여 준다(상태는 안 바뀜) | Must | 1 |
| F4 | 반납 처리: 점검표를 확정하면 상태가 반납 완료로 바뀌고 청구 내역이 남는다 | Must | 1 |
| F5 | API: `GET /api/users` · `GET /api/rentals?viewer=` · `GET /api/rentals/{rental_id}?viewer=` · `POST /api/rentals/{rental_id}/quote` · `POST /api/rentals/{rental_id}/return` | Must | 1 |

## 4. 화면

한 페이지(`/`). 위 사용자 선택, 왼쪽 대여 목록, 오른쪽 선택한 대여 건의 반납 점검표와 요금.

- **사용자 선택:** `data-testid="user"` (`<select>`, option 의 value 는 user_id). 처음엔 첫 번째 사용자.
- **대여 줄:** `data-testid="rental"` + `data-id`(rental_id) + `data-status`(out · returned). 안에 차량 번호 · 고객 이름 · 반납 예정 시각. 누르면 오른쪽에 점검표.
- **점검표(직원만):** 반납 시각 `data-testid="returned-at"`(`<input>`, 비우면 지금) · 연료 칸 `data-testid="fuel"`(`<select>` 0~8) · 주행거리 `data-testid="km"`(`<input>`) · 손상 추가 `data-testid="add-damage"` 로 줄을 더한다(부위 `dmg-part`(`<select>`: 앞범퍼 · 뒷범퍼 · 운전석문 · 조수석문 · 보닛 · 트렁크 · 앞유리 · 휠) · 등급 `dmg-grade`(`<select>`: minor · major · severe) · 사진 수 `dmg-photos`(`<input>`)) · 미리보기 `data-testid="quote"` · 반납 처리 `data-testid="return"`.
- **대여 전 손상:** `data-testid="pre-damage"` 줄 — 이 대여 건의 `pre_damages`(부위) 를 점검표 위에 보여 준다. 같은 부위를 신고하면 요금에 '기존 손상 · 청구 없음' 으로 표시된다.
- **요금 상자:** `data-testid="fee-late"` · `fee-fuel` · `fee-damage` · `fee-total` — 안에 숫자(원). 미리보기 · 반납 처리 응답을 그대로 그린다.
- **고객 화면:** 점검표 · 미리보기 · 반납 처리 버튼이 **없다.** 반납 완료 건을 누르면 청구 내역(요금 상자)만 보인다.
- **메시지 줄:** `data-testid="message"` — 서버가 거부하면 `detail` 그대로.
- **오류 상태:** API 가 실패하면 `불러오지 못했습니다` 와 다시 시도 버튼.
- 문구를 테스트하는 요소는 그 문구가 **손잡이 요소 안에** 있어야 한다.

## 5. 데이터

- **원본:** 프로젝트 루트 `seed/` CSV 4개. 서버는 **시작할 때마다** CSV 를 읽어 SQLite(`rent.db`)를 **새로** 만든다. 반납 처리 · 청구는 DB 에 쓴다(서버가 도는 동안 유지).

| 파일 | 칸 | 형식과 예시 |
|---|---|---|
| `seed/users.csv` | `user_id, name, role` | `user_id` 문자열 `c1` · `role` `customer`(고객) 또는 `staff`(직원) |
| `seed/cars.csv` | `car_id, plate, model` | `car_id` 문자열 `V-01` · `plate` `12가 3456` · `model` `소형 SUV` |
| `seed/rentals.csv` | `rental_id, car_id, customer_id, out_at, due_at, out_fuel, out_km, status` | `rental_id` 문자열 `R-1001` · `out_at` · `due_at` `YYYY-MM-DD HH:MM` · `out_fuel` 대여 때 연료 칸 0~8 정수 · `out_km` 대여 때 주행거리 정수 · `status` `out`(대여 중) 또는 `returned`(반납 완료) |
| `seed/pre_damages.csv` | `rental_id, part` | 대여 전 점검에서 이미 있던 손상 부위 — 한 줄에 하나 (`R-1001, 앞범퍼`) |

- **반납 기록**(서버가 만든다): `rt_returns(rental_id, returned_at, fuel, km, late_minutes, late_fee, fuel_fee, damage_fee, total, by)` · `rt_damages(rental_id, part, grade, photos, fee, pre_existing)`.
- **테이블:** 접두어 `rt_` — `rt_users` · `rt_cars` · `rt_rentals` · `rt_pre_damages` · `rt_returns` · `rt_damages`.
- **가상 데이터:** 고객 4명 · 직원 1명, 차량 4대, 대여 6건(반납 예정이 지난 것 · 곧 다가오는 것 · 내일 · 이미 반납 완료된 것, 대여 전 손상이 있는 건 2개 이상). **같은 CSV 를 다른 내용으로 바꿔 끼울 수 있어야** 한다.
- **API**
  - `GET /api/users` → `[{"user_id","name","role"}]`
  - `GET /api/rentals?viewer=c1` → `[{"rental_id","car_id","plate","model","customer_id","customer_name","out_at","due_at","out_fuel","out_km","status","pre_damages":[부위…]}]` — 고객이면 자기 것만, 직원이면 전부. 반납 예정 시각 순
  - `GET /api/rentals/{rental_id}?viewer=c1` → 위 한 건 + 반납 완료면 `"charges": {"returned_at","fuel","km","late_minutes","late_fee","fuel_fee","damage_fee","total","damages":[{"part","grade","photos","fee","pre_existing"}]}` (대여 중이면 `"charges": null`)
  - `POST /api/rentals/{rental_id}/quote` 본문 `{"user":"s1","returned_at":"2026-10-25 14:40"(없으면 지금),"fuel":4,"km":12840,"damages":[{"part":"앞범퍼","grade":"minor","photos":2}]}` → 200 `{"late_minutes","late_fee","fuel_fee","damage_fee","total","damages":[…]}` — 상태는 바뀌지 않는다
  - `POST /api/rentals/{rental_id}/return` 같은 본문 → 201 같은 모양 + `"status":"returned"` — 상태가 바뀌고 청구가 남는다
  - 거부 응답은 모두 `{"detail": "사유"}`.

## 6. 업무 규칙

| 번호 | 규칙 |
|---|---|
| R1 | **지연 요금.** 반납 시각이 `due_at` 보다 늦은 분 수가 `late_minutes`. **30분까지는 유예(0원).** 31분부터 **시작된 1시간마다 10,000원**(31분 → 10,000 · 61분 → 20,000). **상한 80,000원**(한 건에 아무리 늦어도 80,000). 일찍 돌려줘도 환불 없음. |
| R2 | **연료 요금.** 반납 연료 칸이 `out_fuel` 보다 적으면 **모자란 칸당 15,000원**. 더 많이 채워 와도 0원(환불 없음). 연료 칸은 0~8 정수 — 아니면 400 `연료 칸은 0~8 입니다`. |
| R3 | **손상 요금.** 등급별 정액: `minor` **30,000** · `major` **150,000** · `severe` **500,000**. 등급이 셋 중 하나가 아니면 400 `손상 등급을 확인하세요`. |
| R4 | **대여 전 손상은 청구하지 않는다.** 신고한 부위가 그 대여 건의 `pre_damages` 에 있으면 그 항목은 `fee` 0 · `pre_existing` true 로 **남기되 청구하지 않는다**(지우지 않는다 — 기록은 남긴다). 같은 부위를 두 번 신고하면 400 `같은 부위가 두 번 있습니다`. |
| R5 | **사진 없는 손상은 받지 않는다.** 손상 항목마다 `photos` 가 1 이상 정수여야 한다 — 아니면 400 `손상 사진이 없습니다 (부위)`. 대여 전 손상이어도 같다. |
| R6 | **주행거리.** `km` 는 `out_km` 이상 정수 — 적으면 400 `주행거리가 대여 때보다 적습니다`. 주행거리 요금은 없다(장거리 요금은 8 범위 밖). |
| R7 | **상태.** `quote` · `return` 은 상태 `out` 에서만 — `returned` 면 409 `이미 반납 처리된 건입니다`. `return` 은 한 번만. `returned_at` 은 `out_at` 보다 앞설 수 없다 — 앞서면 400 `반납 시각이 대여 시각보다 앞입니다`. |
| R8 | **권한.** `quote` · `return` 은 직원만 — 고객이면 403 `직원만 할 수 있습니다`. 고객은 자기 대여 건만 본다 — 남의 건 `GET /api/rentals/{id}` 는 403 `본인 대여 건만 볼 수 있습니다`, 목록은 자기 것만. |
| R9 | **입력과 거부 순서.** `user`(또는 `viewer`)가 문자열로 없으면 400 `사용자를 확인하세요`. 거부가 둘 이상이면 **'무엇을 찾아야 알 수 있나'** 순서로 하나만: 본문만 보면 아는 것(400: 사용자 없음 · 연료 칸 범위 · 등급 · 사진 수 · 같은 부위 두 번) → 없는 사용자 · 대여 건(404) → 사용자를 찾아야 아는 권한(403) → 대여 건을 찾아야 아는 400(주행거리 · 반납 시각) → 상태(409). |

**합계:** `total = late_fee + fuel_fee + damage_fee`. 금액은 모두 정수(원).

## 7. 제약

- 스택: **Python FastAPI + 순수 HTML/JS(프레임워크 · 빌드 도구 없음) + SQLite.**
- 실행: 프로젝트 루트에서 `python -m uvicorn main:app --port 8000` (`main.py` 에 `app = FastAPI()`). 포트는 환경 변수 `PORT` 가 있으면 그것. **`main.py` 안에서 다른 파일을 import 하면 프로젝트 루트 기준 절대 경로로**(테스트는 다른 폴더에서 서버를 띄운다).
- '지금' 은 서버 로컬 시각. 시각 문자열은 `YYYY-MM-DD HH:MM`. 외부 네트워크 · CDN 없음. 외부 패키지는 `fastapi` · `uvicorn` 만. 한글 UI.

## 8. 범위 밖 (Won't)

- 로그인 · 회원가입, 예약 · 배차 · 대여 시작 처리(대여 건은 CSV 로만), 결제 · 영수증, 사진 파일 업로드(사진은 **장수만** 적는다), 장거리 · 주행거리 요금, 보험 · 면책, 사고 접수, 정비 일정, 문자 · 알림, 통계, **차량 · 고객 편집 화면(데이터 편집 화면)**, 다크 모드.

## 9. 개발 단계

1. **Phase 1:** `seed/` → SQLite, API 5개와 규칙 R1~R9, `/` 화면(사용자 · 대여 목록 · 점검표 · 요금 상자 · 메시지 · 오류).
2. 그 외 없음.

## 10. 완료 기준 (DoD)

`tests/test_dod.py` 가 완료 기준이다. 아래 9개가 모두 통과해야 끝난다.

- [ ] T1 `/` 가 200 으로 열리고 '반납' 이 보인다.
- [ ] T2 사용자 5명 · 대여 목록(반납 예정 순, 고객은 자기 것만 · 직원은 전부, `pre_damages` 포함) · 한 건 조회(대여 중이면 `charges` null) 가 계약대로.
- [ ] T3 지연 요금: 유예 30분 안은 0 · 31분은 10,000 · 150분은 30,000 · 30시간은 80,000(상한) · 일찍 반납은 0 (R1).
- [ ] T4 연료 요금: 6칸으로 나가 4칸이면 30,000 · 7칸이면 0 · 9칸은 400 (R2).
- [ ] T5 손상 요금: minor + major + severe = 680,000 · 대여 전 손상 부위는 fee 0 · pre_existing true · 사진 0은 400 · 같은 부위 두 번은 400 · 등급 오타는 400 (R3 · R4 · R5).
- [ ] T6 반납 처리: 미리보기로 상태가 안 바뀌고, 반납 처리는 201 · 상태 returned · 합계가 미리보기와 같고, 한 건 조회에 `charges` 가 남는다 (R7).
- [ ] T7 상태 · 시각: 반납 처리한 건에 다시 반납은 409, 미리보기도 409, 대여 시각보다 앞선 반납 시각은 400, 주행거리가 대여 때보다 적으면 400 (R6 · R7).
- [ ] T8 권한 · 거부 순서: 고객의 미리보기는 403, 고객이 남의 건 조회는 403, 본문에 user 없음 + 없는 건은 400, 없는 건은 404, 고객이 주행거리를 잘못 넣어도 403 이 먼저, 직원이 연료 9 + 없는 건이면 400 이 먼저 (R8 · R9).
- [ ] T9 화면: 직원으로 대여 중 건을 누르면 점검표(연료 · 주행거리 · 손상 추가)와 대여 전 손상 줄이 보이고, 미리보기를 누르면 요금 상자에 합계 숫자가 뜬다. 고객에게는 점검표 · 반납 처리 버튼이 없다.
