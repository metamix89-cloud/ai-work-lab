# -*- coding: utf-8 -*-
import lab
print("S3 기대:", lab.pick("선택: S3\n이유..."), lab.pick("**선택: S2**"), "S2 기대")
good = "지난 6개월 데이터 400건(냉동 · 변질 포함)을 다시 판정하고, 담당자 2명이 1주일간 실제 반품에 참고만 하며 처리 시간을 기록. 자동 환불 없이 최종 결정은 사람. 일치율 85% 미달이면 중단."
print("frozen real staff stop True · auto False 기대:", lab.proposal_checks(good))
bad = "상온 박스 파손 사진만 과거 데이터 300건으로 시험 (냉동 · 변질은 2단계에서). 성공하면 '파손 맞음'이면 자동 환불 적용."
print("frozen False · auto True 기대:", lab.proposal_checks(bad))
p2 = "1. 무엇을\n- '상온 상품 박스 파손' 유형 건에 한정해 시범 운영\n2. 어떤 데이터로\n- 300건\n3. 누가\n- 담당자\n이후 냉동·냉장 변질 유형 확장"
print("상온 한정 → frozen False 기대:", lab.covers_frozen(p2))
