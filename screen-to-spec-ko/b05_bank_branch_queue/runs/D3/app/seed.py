"""가상 데이터. 이름 · 번호는 모두 임의의 가상 값이다. 기준은 '지금' 시각."""
from datetime import timedelta

from . import core

NAMES = ["김민수", "이서연", "박지훈", "최유나", "정다은", "한상우", "오세진", "윤하늘", "장보라", "서지호",
         "남궁민", "강현", "임수빈", "조은", "신예린", "권태양", "송가람", "류재민"]


def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]:
        return
    t = core.now()
    m = lambda x: t + timedelta(minutes=x)
    i = [0]

    def person(service):
        i[0] += 1
        n = NAMES[(i[0] - 1) % len(NAMES)]
        return n, f"010-0000-{1000 + i[0]:04d}", f"{(i[0] * 7919) % 10000:04d}", service

    def add(kind, service, reserved=None, arrive=None, status="waiting", window=None, called=None):
        n, p, a, s = person(service)
        with core.lock:
            if kind == "walkin":
                vid = conn.execute("INSERT INTO visits(kind,name,phone,account_last4,service,status)"
                                   " VALUES('walkin',?,?,?,?,'waiting')", (n, p, a, s)).lastrowid
            else:
                code = core.create_reservation(conn, n, p, a, s, reserved)
                vid = conn.execute("SELECT id FROM visits WHERE code=?", (code,)).fetchone()[0]
            if arrive is not None:
                core._arrive(conn, vid, arrive)
            if status in ("called", "serving", "done", "hold"):
                conn.execute("UPDATE visits SET status=?, window=?, called_at=? WHERE id=?",
                             (status, window, core.ts(called or t), vid))

    # 일반 현장 고객 (먼저 도착)
    add("walkin", "deposit", arrive=m(-25))
    add("walkin", "deposit", arrive=m(-20))
    add("walkin", "loan", arrive=m(-18))
    add("walkin", "fx", arrive=m(-15))
    # 예약 고객: 예약 시각 ±10분 안에 도착 -> 우선
    add("reservation", "deposit", reserved=m(-8), arrive=m(-5))
    add("reservation", "loan", reserved=m(-6), arrive=m(-4))
    # 예약 고객: 30분 늦게 도착 -> 일반 순서
    add("reservation", "deposit", reserved=m(-40), arrive=m(-3))
    # 예약했지만 아직 안 옴 (곧 도착 예정 / 이미 노쇼)
    add("reservation", "fx", reserved=m(20))
    add("reservation", "deposit", reserved=m(45))
    add("reservation", "loan", reserved=m(-30))
    # 오늘 처리 완료 / 보류
    add("walkin", "deposit", arrive=m(-90), status="done", window=1, called=m(-85))
    add("walkin", "deposit", arrive=m(-80), status="done", window=2, called=m(-75))
    add("walkin", "fx", arrive=m(-70), status="done", window=4, called=m(-66))
    add("walkin", "loan", arrive=m(-60), status="hold", window=3, called=m(-55))
    # 지금 호출/응대 중
    add("walkin", "deposit", arrive=m(-35), status="serving", window=1, called=m(-9))
    add("walkin", "deposit", arrive=m(-30), status="called", window=2, called=m(-1))
