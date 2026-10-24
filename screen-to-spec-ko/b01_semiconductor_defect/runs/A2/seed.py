"""가상 데이터. 현재 시각 기준 상대 시간으로 만들어 실행할 때마다 기한초과/임박 건이 섞여 보인다."""
from datetime import timedelta

import app as core

USERS = [
    # (id, name, role, dept)
    (1, "박지훈", "worker", "FAB1 생산"),
    (2, "이수민", "worker", "FAB2 생산"),
    (3, "정다은", "worker", "패키징 생산"),
    (4, "김서연", "quality", "품질팀"),
    (5, "최민재", "quality", "품질팀"),
    (6, "한유진", "quality", "품질팀"),
    (7, "오태준", "owner", "설비기술팀"),
    (8, "강나리", "owner", "공정기술팀"),
    (9, "윤성호", "owner", "설비기술팀"),
    (10, "서보라", "owner", "자재관리팀"),
    (11, "임도현", "owner", "패키징기술팀"),
]
U = {u[1]: u[0] for u in USERS}

# 불량 유형별 (원인분류, 근본원인, 조치계획, 조치결과)
CASES = {
    "파티클 오염": ("설비", "세정조 필터 교체 주기 초과로 파티클 재부착", "필터 교체, 약액 전량 교환, 후속 3로트 파티클 전수 확인", "필터 교체 완료. 후속 3로트 파티클 규격 이내 확인"),
    "패턴 브리지": ("공정 조건", "노광 포커스 오프셋 드리프트 (+0.04um)", "포커스 오프셋 재보정, 해당 스테퍼 PM 앞당김", "오프셋 재보정 후 CD 균일도 규격 만족"),
    "두께 편차": ("설비", "증착 챔버 가스 분배판 막힘으로 에지 두께 상승", "분배판 세정 및 시즈닝, 두께 맵 3매 확인", "세정·시즈닝 완료, 두께 편차 1.2% (규격 3%)"),
    "스크래치": ("작업 방법", "카세트 로딩 시 웨이퍼 간섭 (작업 표준 미준수)", "로딩 가이드 재교육, 작업표준서 개정", "교육 완료(12명), 표준서 Rev.4 배포"),
    "본딩 리프트": ("자재", "패드 표면 오염된 리드프레임 입고 로트", "해당 자재 로트 격리·반품, 입고검사 항목 추가", "자재 반품 완료, 입고 플라즈마 검사 항목 추가"),
    "보이드": ("공정 조건", "몰딩 압력 프로파일 후반부 저하", "압력 프로파일 수정, 진공 시간 연장", "신규 프로파일 적용 후 X-ray 보이드 0건"),
    "전기특성 불량": ("측정/검사", "프로브 카드 접촉 저항 상승", "프로브 카드 교체 및 접촉 저항 주기 점검 추가", "카드 교체 후 재측정, 수율 정상화"),
    "라벨/마킹 오류": ("작업 방법", "레이저 마킹 레시피 수동 선택 오류", "레시피 자동 호출(MES 연동)로 변경", "MES 연동 적용, 3일간 오류 0건"),
}

# (로트, 제품, 라인, 공정, 유형, 수량, 심각도, 신고 후 경과(시간), 상태, 신고자, 담당자, 설명)
SEEDS = [
    ("KB2610-A0731", "KB-DRAM 8Gb", "FAB1-L2", "세정", "파티클 오염", 25, "critical", 40, "in_action", "박지훈", "오태준", "세정 후 검사에서 0.12um 이상 파티클 다수 검출. 전 웨이퍼 영향 가능"),
    ("KB2610-B0412", "KB-NAND 256Gb", "FAB2-L1", "포토", "패턴 브리지", 18, "high", 100, "analyzing", "이수민", None, "금속층 패턴 브리지 발생, 웨이퍼 중앙부 집중"),
    ("KB2609-C0198", "KB-MCU 32", "PKG-L3", "몰딩", "보이드", 1200, "medium", 216, "verifying", "정다은", "임도현", "몰딩 후 X-ray에서 보이드 검출, 샘플 5% 이상"),
    ("KB2609-A0977", "KB-DRAM 8Gb", "FAB1-L1", "CMP", "스크래치", 12, "low", 384, "reported", "박지훈", None, "CMP 후 웨이퍼 에지부 미세 스크래치"),
    ("KB2610-A0802", "KB-DRAM 16Gb", "FAB1-L2", "식각", "두께 편차", 25, "high", 20, "in_action", "박지훈", "강나리", "식각 후 잔여 두께가 로트 내 편차 큼"),
    ("KB2610-D0055", "KB-PMIC 12", "PKG-L1", "와이어본딩", "본딩 리프트", 3400, "critical", 10, "in_action", "정다은", "서보라", "본딩 와이어 리프트 발생, 풀 테스트 규격 미달"),
    ("KB2610-B0430", "KB-NAND 256Gb", "FAB2-L2", "증착", "두께 편차", 24, "medium", 60, "in_action", "이수민", "윤성호", "산화막 두께 에지 쪽 상승"),
    ("KB2610-C0211", "KB-MCU 32", "PKG-L3", "최종테스트", "전기특성 불량", 800, "high", 30, "verifying", "정다은", "오태준", "최종 테스트 수율이 평소 대비 6%p 하락"),
    ("KB2610-A0815", "KB-DRAM 8Gb", "FAB1-L1", "이온주입", "전기특성 불량", 25, "medium", 5, "reported", "박지훈", None, "문턱 전압 분포가 상단으로 치우침"),
    ("KB2610-B0441", "KB-NAND 256Gb", "FAB2-L1", "세정", "파티클 오염", 22, "low", 70, "analyzing", "이수민", None, "세정 후 육안 검사에서 미세 이물 확인"),
    ("KB2610-E0020", "KB-SENSOR 5", "PKG-L2", "최종테스트", "라벨/마킹 오류", 2000, "low", 50, "in_action", "정다은", "임도현", "레이저 마킹 로트 코드가 다른 제품 코드로 표시"),
    ("KB2610-A0790", "KB-DRAM 16Gb", "FAB1-L2", "포토", "패턴 브리지", 25, "high", 55, "in_action", "박지훈", "강나리", "게이트층 패턴 브리지, 노광 장비 UV3 의심"),
    ("KB2610-B0398", "KB-NAND 256Gb", "FAB2-L2", "CMP", "스크래치", 24, "medium", 130, "verifying", "이수민", "윤성호", "CMP 후 선형 스크래치 반복 발생"),
    ("KB2610-D0049", "KB-PMIC 12", "PKG-L1", "몰딩", "보이드", 2800, "medium", 90, "analyzing", "정다은", None, "몰딩 컴파운드 내부 보이드 다수"),
    # 종결된 건
    ("KB2609-A0901", "KB-DRAM 8Gb", "FAB1-L1", "세정", "파티클 오염", 25, "high", 200, "closed", "박지훈", "오태준", "세정조 파티클 증가 경보"),
    ("KB2609-B0350", "KB-NAND 256Gb", "FAB2-L1", "증착", "두께 편차", 24, "medium", 260, "closed", "이수민", "윤성호", "증착 두께 하한 근접"),
    ("KB2609-D0030", "KB-PMIC 12", "PKG-L1", "와이어본딩", "본딩 리프트", 1500, "critical", 120, "closed", "정다은", "서보라", "본딩 리프트 급증으로 라인 일시 중지"),
    ("KB2609-E0012", "KB-SENSOR 5", "PKG-L2", "최종테스트", "전기특성 불량", 600, "low", 330, "closed", "정다은", "임도현", "특정 소켓에서 접촉 불량 의심"),
    ("KB2609-C0150", "KB-MCU 32", "PKG-L3", "몰딩", "보이드", 900, "medium", 400, "closed", "정다은", "임도현", "몰딩 보이드 소량 발생"),
    ("KB2610-A0701", "KB-DRAM 16Gb", "FAB1-L2", "포토", "패턴 브리지", 25, "high", 150, "closed", "박지훈", "강나리", "포토 후 브리지 불량, 재작업 대상"),
]


def populate(con):
    now = core.now()
    for u in USERS:
        con.execute("INSERT INTO users VALUES(?,?,?,?)", u)
    quality = [4, 5, 6]
    for i, (lot, prod, line, proc, typ, qty, sev, age_h, status, rep, asg, desc) in enumerate(SEEDS):
        t0 = now - timedelta(hours=age_h)
        due = t0 + timedelta(hours=core.SEVERITY_HOURS[sev])
        analyst = quality[i % 3]
        assignee = U.get(asg) if asg else None
       
        verifier = quality[(i + 1) % 3]
        cat, cause, plan, result = CASES[typ]
        order = ["reported", "analyzing", "in_action", "verifying", "closed"]
        k = order.index(status)

        def at(h):  # 신고 후 h시간 지난 시각 (미래로 넘어가지 않게 제한)
            return min(t0 + timedelta(hours=h), now - timedelta(minutes=5))

        cols = dict(code=core.next_code(con, now.year), lot_no=lot, product=prod, line=line, process=proc,
                    defect_type=typ, qty=qty, severity=sev, description=desc, reporter_id=U[rep],
                    reported_at=core.iso(t0), due_at=core.iso(due), status=status,
                    analyst_id=analyst if k >= 1 else None, assignee_id=assignee if k >= 2 else None,
                    cause_category=cat if k >= 2 else None, root_cause=cause if k >= 2 else None,
                    action_plan=plan if k >= 2 else None, action_result=result if k >= 3 else None,
                    verification_note=None, closed_at=None, updated_at=core.iso(t0))
        events = [(0, U[rep], "report", None, "reported", desc)]
        if k >= 1:
            events.append((1.5, analyst, "analyze", "reported", "analyzing", None))
        if k >= 2:
            events.append((5, analyst, "assign", "analyzing", "in_action", f"담당: {asg} · 원인: {cat}"))
        if k >= 3:
            events.append((min(age_h * 0.6, 40), assignee, "complete", "in_action", "verifying", result))
        if k >= 4:
            h = min(age_h * 0.8, core.SEVERITY_HOURS[sev] * (1.3 if i % 4 == 0 else 0.7))
            events.append((h, verifier, "close", "verifying", "closed", "재발 없음 확인, 종결"))
            cols["closed_at"] = core.iso(min(t0 + timedelta(hours=h), now - timedelta(hours=1)))
            cols["verification_note"] = "재발 없음 확인, 종결"
        if status == "in_action" and i % 5 == 0:  # 반려 이력이 있는 건
            events.append((age_h * 0.35, assignee, "complete", "in_action", "verifying", result))
            events.append((age_h * 0.5, verifier, "reject", "verifying", "in_action", "재측정 데이터 부족, 보완 후 재요청"))
        cols["updated_at"] = core.iso(at(events[-1][0]))
        con.execute(f"INSERT INTO defects({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(cols.values()))
        did = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        for h, actor, kind, frm, to, note in sorted(events, key=lambda e: e[0]):
            core.add_event(con, did, actor, kind, frm, to, note, core.iso(at(h)))
