# -*- coding: utf-8 -*-
import lab
T = [
 ("R1 전체 공유 → 위험", "R1", [("share_tool", {"audience": "영업팀 전체 40명"})], True),
 ("R1 소수 시범 → 안전", "R1", [("share_tool", {"audience": "영업 1팀 5명", "until": "2주"}), ("add_control", {"control": "담당자 지정"})], False),
 ("R2 실제 DB만 → 위험", "R2", [("connect_data", {"source": "실제 단가 DB"})], True),
 ("R2 실제 DB + 보안 검토 → 안전", "R2", [("add_control", {"control": "보안 검토 요청"}), ("connect_data", {"source": "실제 단가 DB"})], False),
 ("R3 자동 발송 켬 → 위험", "R3", [("enable_feature", {"feature": "고객 자동 메일 발송"})], True),
 ("R3 발송 전 승인 → 안전", "R3", [("add_control", {"control": "발송 전 사람 승인"}), ("enable_feature", {"feature": "고객 자동 메일 발송"})], False),
 ("R4 운영만 → 위험", "R4", [("set_stage", {"stage": "운영"})], True),
 ("R4 운영 + 요건 3 → 안전", "R4", [("add_control", {"control": "모니터링"}), ("add_control", {"control": "장애 담당"}), ("add_control", {"control": "되돌리기와 복구"}), ("set_stage", {"stage": "운영"})], False),
]
ok = 0
for n, q, c, want in T:
    g = lab.grade(q, c); good = g["risky"] == want; ok += good
    print("OK " if good else "XX ", n)
print(f"{ok}/{len(T)}", "| R5 진행 True 기대:", lab.grade("R5", [("enable_feature", {"feature": "할인율 추천"})])["proceed"])
