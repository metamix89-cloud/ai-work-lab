# PRD — 다온소프트 「신입사원 온보딩 교육」

> 「이 화면, PRD 로는 이렇게」 9편. 회사 · 직원 · 교육 내용 · 퀴즈는 모두 교육용 가상 데이터.
> 형식은 10칸(개요 · 사용자 · 기능 · 화면 · 데이터 · 업무 규칙 · 제약 · 범위 밖 · 개발 단계 · 완료 기준).

## 1. 개요

- **배경:** 다온소프트는 신입사원에게 첫 주 온보딩 영상 4개와 확인 퀴즈를 메일로 보낸다. 누가 어디까지 봤는지 인사팀이 일일이 묻고, 퀴즈 정답이 담긴 파일이 돌아다닌다.
- **목적:** 신입은 **레슨 4개를 순서대로** 마치고 **퀴즈 80점 이상이면 수료**한다. 신입은 **자기 진도만** 보고, 인사팀(관리자)은 **미수료자 목록**을 진도 낮은 순으로 본다. 퀴즈 정답은 화면 · API 어디에도 나가지 않는다.
- **성공 기준:** "어디까지 했어요?" 질문 0건. 정답 유출 0건.

## 2. 사용자

- **신입(trainee)** 과 **관리자(admin)** 두 역할. 로그인 없이 화면 위 **사용자 선택 상자**에서 고른다(역할은 `seed/users.csv` 의 `role`). API 는 요청자를 `viewer`(조회) 또는 `user`(본인 행동)로 받는다.

## 3. 기능 요구사항

| 번호 | 기능 | MoSCoW | Phase |
|---|---|---|---|
| F1 | 내 진도: 레슨 4개(완료 · 열림 · 잠김), 진도율, 퀴즈 응시 횟수 · 최고 점수, 수료 여부 | Must | 1 |
| F2 | 레슨 완료 표시: '다 봤어요' 버튼 — 순서대로만 | Must | 1 |
| F3 | 퀴즈: 레슨 4개를 마치면 열림. 5문항 4지선다, 제출하면 서버가 채점 | Must | 1 |
| F4 | 관리자 미수료자 목록: 이름 · 진도율 · 응시 횟수 · 최고 점수, 진도율 낮은 순 | Must | 1 |
| F5 | API: `GET /api/users` · `GET /api/lessons` · `GET /api/quiz` · `GET /api/progress` · `POST /api/lessons/{id}/complete` · `POST /api/quiz/submit` · `GET /api/admin/incomplete` | Must | 1 |

## 4. 화면

한 페이지(`/`).

- **위:** 제목 `다온소프트 온보딩 교육`, 사용자 선택(`data-testid="user-select"`). 고른 사용자가 관리자면 관리자 화면, 신입이면 신입 화면.
- **신입 화면:** 진도율(`data-testid="progress"`, `50%` 처럼 숫자와 %), 레슨 행 `data-testid="lesson"` + `data-id`(L1~L4) + `data-state`(`done` | `open` | `locked`), 열린 레슨에만 완료 버튼(`data-testid="complete-btn"`). 퀴즈 영역(`data-testid="quiz"`)은 레슨 4개를 마쳤을 때만 보이고, 문항마다 보기 4개, 제출(`data-testid="submit-btn"`), 결과(`data-testid="result"` — 점수 · 합격/불합격 · 남은 응시 횟수). 수료하면 `data-testid="certified"` 에 `수료`.
- **관리자 화면:** 미수료자 행 `data-testid="incomplete-row"` + `data-user` + `data-progress`(0~100 정수). 신입 화면 요소는 없다.
- **메시지 줄:** `data-testid="message"` — 서버가 거부하면 `detail` 그대로.
- **오류 상태:** API 가 실패하면 `불러오지 못했습니다` 와 다시 시도 버튼.
- 문구를 테스트하는 요소는 그 문구가 **손잡이 요소 안에** 있어야 한다.

## 5. 데이터

- **원본:** 프로젝트 루트 `seed/` CSV 5개. 서버는 **시작할 때마다** CSV 를 읽어 SQLite(`onboard.db`)를 **새로** 만든다.

| 파일 | 칸 | 형식과 예시 |
|---|---|---|
| `seed/users.csv` | `user, role` | `user` 문자열 이름 `김신입` · `role` `trainee` 또는 `admin` |
| `seed/lessons.csv` | `lesson_id, seq, title` | `lesson_id` 문자열 `L1` · `seq` 1부터 정수(순서) |
| `seed/questions.csv` | `q_id, text, choices, answer` | `q_id` 문자열 `Q1` · `choices` 보기 4개를 `|` 로 이은 문자열 `연차|반차|병가|출장` · `answer` 정답 보기의 번호 0~3 정수 |
| `seed/progress.csv` | `user, lesson_id, completed_at` | `completed_at` `YYYY-MM-DD HH:MM` |
| `seed/attempts.csv` | `user, attempt, score, passed, at` | `attempt` 1부터 정수 · `score` 0~100 정수 · `passed` `1`/`0` · `at` `YYYY-MM-DD HH:MM` |

- **테이블:** 접두어 `ob_` — `ob_users` · `ob_lessons` · `ob_questions` · `ob_progress` · `ob_attempts`. 칸은 CSV 와 같다.
- **가상 데이터:** 직원 4명(관리자 1), 레슨 4개, 문항 5개, 진도 · 응시 기록 몇 줄. **같은 CSV 를 다른 내용으로 바꿔 끼울 수 있어야** 한다.
- **API**
  - `GET /api/users` → `[{"user":"김신입","role":"trainee"}, ...]`
  - `GET /api/lessons` → `[{"lesson_id":"L1","seq":1,"title":"..."}, ...]` seq 순.
  - `GET /api/quiz` → `[{"q_id":"Q1","text":"...","choices":["연차","반차","병가","출장"]}, ...]` — **정답 칸이 없다.**
  - `GET /api/progress?user=김신입&viewer=김신입` → `{"user","lessons":[{"lesson_id","state":"done|open|locked"}],"progress":50,"attempts":1,"best_score":60,"passed":false,"certified":false,"attempts_left":2}`
  - `POST /api/lessons/{lesson_id}/complete` 본문 `{"user":"김신입"}` → 200 과 progress.
  - `POST /api/quiz/submit` 본문 `{"user":"김신입","answers":[0,1,2,3,0]}` → 200 `{"score":80,"passed":true,"attempt":2,"attempts_left":1,"certified":true}` — **어느 문항이 틀렸는지 · 정답은 돌려주지 않는다.**
  - `GET /api/admin/incomplete?viewer=최인사` → `[{"user","progress","attempts","best_score"}]` 진도율 낮은 순, 같으면 이름 순.
  - 거부 응답은 모두 `{"detail": "사유"}`.

## 6. 업무 규칙

| 번호 | 규칙 |
|---|---|
| R1 | **레슨은 순서대로.** `seq` 가 앞선 레슨을 모두 마쳐야 다음 레슨을 완료할 수 있다. 아니면 409 `이전 레슨을 먼저 마치세요`. 이미 마친 레슨을 다시 완료하면 200(변화 없음). |
| R2 | **퀴즈는 레슨 4개를 다 마친 뒤.** 아니면 409 `레슨을 모두 마친 뒤 응시할 수 있습니다`. |
| R3 | **채점은 서버.** 점수 = 맞은 문항 수 × 100 ÷ 문항 수(정수). **80 이상이면 합격 — 80 은 합격이다.** |
| R4 | **응시는 3회까지, 합격하면 끝.** 4번째 제출 또는 합격 뒤 제출은 409 `더 응시할 수 없습니다`. |
| R5 | **진도율** = 마친 레슨 수 × 100 ÷ 레슨 수(정수, 퀴즈는 포함 안 함). **수료** = 레슨을 모두 마치고 합격. 3회 모두 떨어지면 미수료로 남는다(재응시 허용은 범위 밖). |
| R6 | **신입은 자기 것만.** `viewer` 가 `user` 와 다르고 관리자도 아니면 403 `본인 진도만 볼 수 있습니다`. `admin/incomplete` 는 관리자만 — 아니면 403. |
| R7 | **정답은 나가지 않는다.** `GET /api/quiz`, 채점 결과, 화면 어디에도 정답 보기 번호 · 문항별 정오가 없다. |
| R8 | **거부가 둘 이상 해당하면** 400(입력 오류: answers 가 문항 수만큼의 0~3 정수가 아님 등) → 403(권한) → 404(없는 사용자 · 레슨) → 409(흐름 위반) 순서로 먼저 걸리는 것 하나만. |

## 7. 제약

- 스택: **Python FastAPI + 순수 HTML/JS(프레임워크 · 빌드 도구 없음) + SQLite.** 동영상 재생은 없다(레슨은 제목과 본문 글 두세 줄, '다 봤어요' 버튼).
- 실행: 프로젝트 루트에서 `python -m uvicorn main:app --port 8000` (`main.py` 에 `app = FastAPI()`). 포트는 환경 변수 `PORT` 가 있으면 그것.
- 외부 네트워크 · CDN 없음. 외부 패키지는 `fastapi` · `uvicorn` 만. 한글 UI.

(실측 뒤 메모: 이 PRD 는 스스로 모순된다 — ① 7 제약 '레슨은 본문 글 두세 줄' ↔ 5 데이터 `lessons.csv` 에 본문 칸이 없음, ② R4 '합격하면 끝' ↔ API 예시 '2회째 합격 → attempts_left 1'. B · C 여섯 번 중 다섯이 ①을, 셋이 ②를 찾아 보고했다. 공개본에는 모순을 그대로 둔다 — 9편 영상의 재료.)

## 8. 범위 밖 (Won't)

- 로그인 · 비밀번호, **레슨 · 문항 · 직원 편집 화면(데이터 편집 화면)**, 동영상 업로드 · 재생 시간 측정, 재응시 허용 · 응시 횟수 초기화, 수료증 PDF, 알림 · 메일, 문항 무작위 섞기, 오답 해설, 통계 차트, 다크 모드.

## 9. 개발 단계

1. **Phase 1:** `seed/` → SQLite, API 7개와 규칙 R1~R8, `/` 화면(신입 · 관리자 · 메시지 · 오류).
2. 그 외 없음.

## 10. 완료 기준 (DoD)

`tests/test_dod.py` 가 완료 기준이다. 아래 9개가 모두 통과해야 끝난다.

- [ ] T1 `/` 가 200 으로 열리고 '온보딩' 이 보인다.
- [ ] T2 `GET /api/quiz` 에 문항 5개, 정답 칸이 없다 (R7).
- [ ] T3 순서를 건너뛴 레슨 완료는 409, 다음 레슨은 200, 진도율이 맞다 (R1 · R5).
- [ ] T4 레슨을 다 안 마치고 퀴즈를 내면 409 (R2).
- [ ] T5 5문항 중 4개 맞으면 80점 합격 · 수료, 합격 뒤 다시 내면 409. 결과에 정답 · 문항별 정오가 없다 (R3 · R4 · R7).
- [ ] T6 세 번째에 떨어지면 다음 제출은 409, 미수료로 남는다 (R4 · R5).
- [ ] T7 신입이 남의 진도를 보면 403, 본인 · 관리자는 200, 신입이 미수료자 목록을 보면 403. 없는 사용자 + 잘못된 answers 는 400, 없는 사용자 + 올바른 answers 는 404 (R6 · R8).
- [ ] T8 미수료자 목록이 수료자를 빼고 진도율 낮은 순이다 (R5).
- [ ] T9 화면: 신입을 고르면 레슨 상태(done · open · locked)와 진도율이 맞고, 퀴즈 영역이 없다. 관리자를 고르면 미수료자 행이 보인다.
