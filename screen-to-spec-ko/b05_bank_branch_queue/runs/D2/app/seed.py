"""가상 데이터. 현재 시각 기준 상대 시각으로 만들어 언제 실행해도 화면이 살아 있음."""
from datetime import timedelta

from app.main import add_ticket, iso, now, tx

# (이름, 전화, 계좌, 업무, 종류, 예약 오프셋(분), 도착 오프셋(분), 상태, 창구, 호출 오프셋(분))
ROWS = [
    ("김철수", "010-0000-1273", "110-234-567801", "예금", "walkin", None, -50, "done", 1, -48),
    ("이영희", "010-0000-4958", "220-345-678902", "대출", "reserved", -55, -52, "done", 3, -48),
    ("박민준", "010-0000-1019", "330-456-789003", "외환", "walkin", None, -40, "done", 4, -37),
    ("최수진", "010-0000-8871", "110-567-890104", "예금", "reserved", -35, -33, "done", 2, -30),
    ("홍길동", "010-0000-6913", "110-678-901205", "예금", "walkin", None, -30, "hold", 2, -28),
    ("정우성", "010-0000-3901", "110-789-012306", "예금", "walkin", None, -25, "serving", 1, -20),
    ("강동원", "010-0000-5075", "110-890-123407", "예금", "walkin", None, -22, "waiting", None, None),
    ("윤서연", "010-0000-4090", "110-901-234508", "예금", "walkin", None, -18, "waiting", None, None),
    ("배도현", "010-0000-2769", "440-012-345609", "외환", "walkin", None, -16, "waiting", None, None),
    ("오하늘", "010-0000-6030", "110-123-456710", "예금", "reserved", -40, -15, "waiting", None, None),  # 늦게 도착 → 일반
    ("장민호", "010-0000-8012", "330-234-567811", "대출", "walkin", None, -14, "waiting", None, None),
    ("한지민", "010-0000-6871", "330-345-678912", "대출", "reserved", -20, -12, "serving", 3, -9),
    ("임수아", "010-0000-1533", "440-456-789013", "외환", "reserved", -9, -8, "waiting", None, None),   # 우선
    ("서지후", "010-0000-1482", "110-567-890114", "예금", "reserved", -10, -4, "waiting", None, None),  # 우선
    ("노지훈", "010-0000-3293", "110-678-901215", "예금", "reserved", -5, -3, "called", 2, -1),
]
# 아직 안 온 예약 / 노쇼
PENDING = [
    ("류하준", "010-0000-4746", "110-789-012316", "예금", 15),
    ("신유나", "010-0000-7185", "330-890-123417", "대출", 25),
    ("조현우", "010-0000-4968", "440-901-234518", "외환", 50),
    ("백승호", "010-0000-4152", "110-012-345619", "예금", -90),
    ("남궁민", "010-0000-2942", "330-123-456720", "대출", -60),
]


def seed_if_empty():
    with tx() as c:
        if c.execute("SELECT COUNT(*) FROM tickets WHERE COALESCE(arrived_at, reserved_at)>=?",
                     (iso(now().replace(hour=0, minute=0, second=0)),)).fetchone()[0]:
            return
        base = now()
        at = lambda m: iso(base + timedelta(minutes=m)) if m is not None else None
        for name, phone, acct, svc, kind, res, arr, status, counter, call in sorted(ROWS, key=lambda r: r[6]):
            add_ticket(c, name=name, phone=phone, account=acct, service=svc, kind=kind,
                       reserved_at=at(res), arrived_at=at(arr), status=status, counter=counter,
                       called_at=at(call),
                       finished_at=at(call + 5) if status == "done" else None)
        for name, phone, acct, svc, res in PENDING:
            add_ticket(c, name=name, phone=phone, account=acct, service=svc, kind="reserved",
                       reserved_at=at(res), status="noshow" if res < -30 else "reserved")
