"""가상 데이터 (DB가 비어 있을 때만). 모든 이름·번호는 허구."""
from datetime import timedelta


def seed(m):
    if m.db.execute("SELECT COUNT(*) FROM visits").fetchone()[0]:
        return
    t = m.now()
    P = lambda n, ph, a, s: m.Person(name=n, phone=ph, account=a, service=s)
    M = lambda x: timedelta(minutes=x)

    # 완료 2건
    for n, s in (("한가람", "예금"), ("서지우", "대출")):
        m.insert(P(n, "010-0000-7945", "11112222333344", s), "walkin", "done",
                 ticket=m.next_ticket(), queued=m.iso(t - M(50)))
    # 일반 대기
    for n, ph, a, s, ago in (("김철수", "010-0000-4634", "110123456789", "예금", 12),
                             ("이영희", "010-0000-4420", "110987654321", "대출", 9),
                             ("박민준", "010-0000-5373", "220111222333", "외환", 7),
                             ("최서연", "010-0000-1735", "110555666777", "예금", 4)):
        m.insert(P(n, ph, a, s), "walkin", "waiting", ticket=m.next_ticket(), queued=m.iso(t - M(ago)))
    # 예약 + 창구 안에 도착 → 우선 (예약시각 -3분 도착)
    rt = t - M(2)
    m.insert(P("정다은", "010-0000-1273", "333444555666", "예금"), "reservation", "waiting",
             reserved_at=rt, code="100001", ticket=m.next_ticket(), pri=1, queued=m.iso(rt - M(3)))
    # 예약했지만 30분 늦게 도착 → 일반 순서
    rt = t - M(40)
    m.insert(P("오하준", "010-0000-3249", "444555666777", "대출"), "reservation", "waiting",
             reserved_at=rt, code="100002", ticket=m.next_ticket(), pri=0, queued=m.iso(t - M(5)))
    # 아직 안 온 예약 (곧 도착 가능) / 미래 예약
    m.insert(P("윤서아", "010-0000-7680", "555666777888", "외환"), "reservation", "reserved",
             reserved_at=t + M(5), code="100003")
    m.insert(P("강도현", "010-0000-1160", "666777888999", "예금"), "reservation", "reserved",
             reserved_at=t + M(60), code="100004")
    # 노쇼 (예약 후 10분 넘게 미도착)
    for i, (n, s) in enumerate((("임수빈", "대출"), ("조현우", "예금"))):
        m.insert(P(n, "010-0000-4084", "777888999000", s), "reservation", "noshow",
                 reserved_at=t - M(60 + i * 20), code=f"20000{i}")
    m.db.commit()
    # 창구 3 호출 중 (이영희) → 3분 안에 안 오면 보류되는 모습 확인 가능
    m.call_next_locked(3)
