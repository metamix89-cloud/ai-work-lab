# AI 워크랩 — 영상 속 실험 코드

**Languages:** [English](README.md) · [한국어](README.ko.md)

영상에 나오는 숫자는 모두 이 스크립트로 돌린 결과입니다. 회사 · 고객 · 데이터는 전부 가상입니다.
편마다 `NOTES.md`(결과 · 우리가 한 실수)가 있고, 대개 `test_grade.py`(채점기 자가 시험)가 있습니다.
`.env` 파일에 `OPENAI_API_KEY` 를 넣고(절대 커밋하지 마세요) 각 파일 머리말대로 `python lab.py` 를 실행합니다.
가상 시험 데이터의 전화번호는 공개본에서 `010-0000-xxxx` 자리표시로 바꿨습니다(코드와 결과에서 같은 번호는 같은 자리표시).
이 저장소의 코드는 MIT 라이선스입니다(`LICENSE`). 각색한 원작 과정은 원래 라이선스를 따르며 시리즈마다 적어 두었습니다.

## AI 에이전트 제대로 이해하기 (ep034~046)

원작 bojieli/ai-agent-book — Apache-2.0 — 예시를 새로 만들어 다시 쓴 것으로, 저자의 공식 과정이 아닙니다.

| 편 | 영상 | 폴더 | 무엇을 재는가 |
|---|---|---|---|
| 01_agent_basics | [video](https://youtu.be/0iSV-KVNSj0) | `ai-agent-book-ko/01_agent_basics` | ep034 실습 — 가나다식품 고객 문의 에이전트. 핵심 루프를 프레임워크 없이 직접 짠다. |
| 02_prompt_rules | [video](https://youtu.be/kvBYZtUoa5Y) | `ai-agent-book-ko/02_prompt_rules` | ep035 실습 — 시스템 프롬프트 · 도구 설명이 성능을 바꾸는가 (원서 2장 실험 2-4 방식, 가나다식품 반품 상담으로 각색). |
| 03_agent_skills | [video](https://youtu.be/vWE5A2DKG4g) | `ai-agent-book-ko/03_agent_skills` | ep038 실습 — 스킬을 필요할 때만 펼치기 (원서 2장 실험 2-6 방식, 가나다식품 업무 스킬 9개로 각색). |
| 04_context_compress | [video](https://youtu.be/jA9syaQtgd4) | `ai-agent-book-ko/04_context_compress` | ep039 실습 — 대화가 길어지면: 컨텍스트 압축 전략 비교 (원서 2장 실험 2-10 방식, 가나다식품 거래처 상담 하루로 각색). |
| 05_rag_rules | [video](https://youtu.be/G3vib43f0ug) | `ai-agent-book-ko/05_rag_rules` | ep040 실습 — 사내 규정집 질의: 검색 없음 · 일반 RAG · 혼합 검색 · Agentic RAG (원서 3장 실험 3-6 · 3-8 방식, 가나다식품 규정집으로 각색). |
| 06_tools_safety | [video](https://youtu.be/NEctp4NR0Rk) | `ai-agent-book-ko/06_tools_safety` | ep041 실습 — 도구가 100개면: 전부 넣기 · 미리 골라 넣기 · 필요할 때 찾기 (원서 4장 실험 4-1 방식) + 실행 전 승인 검토자 (4장 사전 승인). |
| 07_rules_as_code | [video](https://youtu.be/JvgLt7Xx0h8) | `ai-agent-book-ko/07_rules_as_code` | ep042 실습 — 규칙은 코드로 (원서 5장 실험 5-5 · 5-13 방식, 가나다식품으로 각색). 모든 데이터는 가상. |
| 08_eval_cost | [video](https://youtu.be/6vtiP_QLcXU) | `ai-agent-book-ko/08_eval_cost` | ep043 실습 — 잘 되는지 어떻게 아나: 평가와 비용 (원서 7장 Pass@k · Pass^k · LLM-as-a-Judge · 실험 7-10 비용 분해, 가나다식품으로 각색). |
| 09_multi_agent | [video](https://youtu.be/8qIvHLS_6i4) | `ai-agent-book-ko/09_multi_agent` | ep044 실습 — 여러 에이전트가 일을 나눌 때 (원서 10장 '멀티 에이전트가 정말 나은 때' 표 10-1 · 실패 모드 '오류의 연쇄 증폭', 가나다식품으로 각색). |
| 10_user_memory | [video](https://youtu.be/NDw1PviT8bQ) | `ai-agent-book-ko/10_user_memory` | ep045 실습 — 보너스 1: 기억하는 에이전트, 사용자 메모리 (원서 3장 '사용자 메모리 · 3단계 평가 · 메모리 저장 형식' · 실험 3-1 · 3-2 방식). |
| 11_computer_use | [video](https://youtu.be/_CXoGzy73mM) | `ai-agent-book-ko/11_computer_use` | ep046 실습 — 보너스 2: 화면을 조작하는 에이전트 (원서 6장 '컴퓨터 사용 · 행동 공간 · 시각적 그라운딩' · 실험 6-9 방식). |

## AI에게 일 맡기기 전에 — 시즌 2 (ep047~058)

원작 rohitg00/ai-engineering-from-scratch — MIT — 예시를 새로 만들어 다시 쓴 것으로, 저자의 공식 과정이 아닙니다.

| 편 | 영상 | 폴더 | 무엇을 재는가 |
|---|---|---|---|
| 01_outcome_first | [video](https://youtu.be/aAH6g5oSMtI) | `ai-engineering-from-scratch-ko/01_outcome_first` | ep047 실습 — 시즌 2 1편: 결과물 말고 성과부터 (원본 Phase 14 레슨 47 'Outcomes before output' · 6칸 성과 틀). |
| 02_real_workflow | [video](https://youtu.be/tk7-q1yGr3k) | `ai-engineering-from-scratch-ko/02_real_workflow` | ep048 실습 — 시즌 2 2편: 실제 업무 흐름 찾기 (원본 Phase 14 레슨 48 'Discover the Workflow People Actually Perform'). |
| 03_riskiest_first | [video](https://youtu.be/2BUlX9mde5g) | `ai-engineering-from-scratch-ko/03_riskiest_first` | ep049 실습 — 시즌 2 3편: 가장 위험한 가정부터 (원본 Phase 14 레슨 49 'Map Assumptions and Resolve the Riskiest One First'). |
| 04_smallest_slice | (아직 미공개) | `ai-engineering-from-scratch-ko/04_smallest_slice` | ep050 실습 — 시즌 2 4편: 가장 작은 시험 조각 (원본 Phase 14 레슨 50 'Choose the Smallest Slice That Can Change the Decision'). |
| 05_judgment_spec | (아직 미공개) | `ai-engineering-from-scratch-ko/05_judgment_spec` | ep051 실습 — 시즌 2 5편: 판단을 남기는 지시서 (원본 Phase 14 레슨 51 'Write Specifications That Preserve Judgment'). |
| 06_success_metrics | (아직 미공개) | `ai-engineering-from-scratch-ko/06_success_metrics` | ep052 실습 — 시즌 2 6편: 성공 기준은 결과 보기 전에 (원본 Phase 14 레슨 52 'Design Success Metrics Before the Result Exists'). |
| 07_stage_drift | (아직 미공개) | `ai-engineering-from-scratch-ko/07_stage_drift` | ep053 실습 — 시즌 2 7편: 시제품 · 시범 · 운영 (원본 Phase 14 레슨 53 'Choose Prototype, Pilot, or Production Deliberately'). |
| 08_task_frame | (아직 미공개) | `ai-engineering-from-scratch-ko/08_task_frame` | ep054 실습 — 시즌 2 8편: 맡기기 전 과제 정의서 (원본 Phase 14 레슨 43 'Frame the Task Before the Agent Writes Code'). |
| 09_evidence_plan | (아직 미공개) | `ai-engineering-from-scratch-ko/09_evidence_plan` | ep055 실습 — 시즌 2 9편: 근거 있는 실행 계획 (원본 Phase 14 레슨 44 'Build an Evidence-Backed Execution Plan'). |
| 10_isolate_work | (아직 미공개) | `ai-engineering-from-scratch-ko/10_isolate_work` | ep056 실습 — 시즌 2 10편: 나눠 맡길 때는 칸을 나눠라 (원본 Phase 14 레슨 45 'Delegate Agent Work with Isolation and Merge Contracts'). |
| 11_feedback_system | (아직 미공개) | `ai-engineering-from-scratch-ko/11_feedback_system` | ep057 실습 — 시즌 2 11편: 같은 지적을 두 번 하지 않으려면 (원본 Phase 14 레슨 46 'Turn Every Agent Correction into a System Improvement'). |
| 12_feedback_ratchet | (아직 미공개) | `ai-engineering-from-scratch-ko/12_feedback_ratchet` | ep058 실습 — 시즌 2 12편: 운영하며 계속 좋아지게 (원본 Phase 14 레슨 54 'Build a Feedback Ratchet with Ownership and Retirement'). |
