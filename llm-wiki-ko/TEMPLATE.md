# LLM 위키 템플릿 — 이 폴더를 그대로 가져다 쓰는 법 (12편)

가나다식품(가상) 12편 동안 쓴 코드를 다른 회사 자료에 붙이는 순서다. 모델은 gpt-4.1-mini, `.env` 에 `OPENAI_API_KEY`.

## 1. 폴더 셋

```
raw/        원본 그대로 (손대지 않는다) — 하위 폴더가 '묶음'(cs · suppliers · customers · meetings · policies · sales · ops)
wiki_*/     위키 한 벌 = 폴더 하나 (pages/*.md · index.md · log.md). 편마다 복사해 두고 이어서 쌓는다
schema*.md  규칙 파일 — 이 위키가 답할 질문 5개, 페이지 종류와 형식, '쓰면 안 되는 것'
```

## 2. 규칙 파일(schema) 은 이 순서로 자란다 — 글로 쓴 규칙은 모델이 안 지킨다, 아래 '코드' 가 진짜 규칙

| 편 | 규칙(글) | 코드 (run_stage.py 옵션 · engine.py) |
|---|---|---|
| 2 | 건수는 세지 말고 표로, 주별 페이지 금지 | `--tally`(tally_table 도구) · `--auto-index`(목차는 코드가 다시 만듦) |
| 3 | 현재 값과 이력 분리, 한 품목 단가는 한 곳 | `--search`(묻기에 search_wiki) · `write_page_keep_history`(이력 · 출처 되살림) |
| 4 | 결정은 다섯 칸(무엇을 · 왜 · 누가 · 기한 · 상태) | `--extract`(extract_decisions 도구가 회의록 결정 사항을 뽑음) |
| 5 | 규정은 조항마다 페이지, 개정은 이력 | `--split-articles`(조항 단위 넣기) · `--amend-last`(개정은 뒤에, 새 페이지 거부) · `--require-write` |
| 6 | 점검은 상충 · 낡음 · 고아 · 빠짐 | `lint_run.py --mode=verify`(코드가 짝 짓고 묶음마다 묻고 후보 검증, 고아는 코드) |
| 8 | 보고서는 질문으로 쪼갠다 | `report_run.py --mode=split` |
| 9 | 등급 낮은 원본(메모 · 초안 · 보고)은 본문을 못 바꾼다 | `conflict_guard=True`(merge_conflict_only — ⚠ 상충 절에만 더함) |
| 10 | 주간 루틴: 날짜 지난 '예정' 을 현재 값으로 | `ops_run.py` 의 routine (overdue_lines → 모델이 옮김) |
| 11 | 개인 식별 정보는 쓰지 않는다 | `--pii-mask`(pii_mask — 전화 · 주민번호 · 사번 · 비밀번호 · 카드 · 연봉 · 상세 주소를 넣기 전에 가림) |

## 3. 처음 한 번

```
python make_sources.py            # (가상 원본을 만드는 스크립트 — 자기 회사 자료면 raw/ 에 넣고 건너뛴다)
python run_stage.py --name=my --groups=cs --qgroups=Q1 --schema=schema_ep5.md --conds=wiki --build-only \
       --tally --auto-index --search --extract --split-articles --amend-last --require-write --pii-mask
python wiki_stats.py wiki_my      # 페이지 · 고아 · 상충 절
python leak_check.py wiki_my      # 민감 정보 지문(자기 회사용 SIG 로 바꿀 것)
```
묶음을 하나씩 더할 때는 `--base=wiki_my --groups=<다음 묶음>` 으로 앞 위키 위에 쌓는다. 질문은 `questions.json` 에 정답 값(must · any · not · none)으로 적고 `grade.py` 가 채점한다 — 채점기는 정답 · 오답 예문으로 먼저 시험한다(`python grade.py`).

## 4. 운영

- 묻기: `engine.query(wiki, 질문, 오늘, search=True)` — 목차 → 검색 → 페이지 8장 → 답 + 근거 줄, 없으면 '위키에 없음'.
- 주간: 새 원본 넣기 → `ops_run.py` 의 루틴(지난 '예정' 옮기기) → 담당 사람은 '상태' 가 둘인 페이지를 본다.
- 점검: `lint_run.py --wiki=wiki_my --mode=verify` — 상충 · 낡음은 모델, 고아 · 빠짐은 코드.
- 교정: 페이지를 고친 뒤 **왜 틀렸는지를 원본 등급으로** 적고, 같은 틀린 메모를 다시 넣어 재발을 센다(`fix_run.py` 꼴).

## 5. 12편 동안 본 숫자 (gpt-4.1-mini, 2026-10-23)

- 50문항 × 3: 규칙 없는 위키 119 → 규칙 위키 142 · 원본 통째 139 · RAG 135 (7편). 위키가 이기는 자리: 이유 · 규정 · 이력. 표 자료 · 보고서는 RAG 로도 충분.
- 문항당 토큰: 위키 13,523 · RAG 2,243 · 통째 33,485. 규칙 위키 쌓는 데 누적 211만 토큰(약 $1), 1편 한 번에 262만.
- 실패는 확률이다 — 같은 조건을 두 번 돌려 흔들림(±6/150)을 알고 비교한다.
