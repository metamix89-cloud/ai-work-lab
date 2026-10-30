"""가상 데이터: 현재 시각 기준으로 대기/호출/노쇼 상황을 만든다."""
from datetime import timedelta


def run(db, issue_number, iso, now):
    n = now()

    def m(x):
        return n + timedelta(minutes=x)

    # (이름, 전화, 계좌, 업무, 예약시각, 도착시각, 상태, 창구, 호출시각)
    rows = [
        ("김민수", "010-0000-4634", "110123456789", "deposit", None, m(-40), "done", 1, m(-35)),
        ("이영희", "010-0000-4420", "110987654321", "loan", m(-45), m(-44), "done", 3, m(-38)),
        ("박철수", "010-0000-5373", "3021234567890", "fx", None, m(-30), "hold", 4, m(-25)),
        ("정수진", "010-0000-1735", "110555566667", "deposit", None, m(-12), "called", 1, m(-1)),
        ("최지훈", "010-0000-1273", "110222233334", "deposit", None, m(-9), "waiting", None, None),
        ("한소희", "010-0000-3249", "110333344445", "deposit", m(-2), m(-8), "waiting", None, None),  # 예약 우선
        ("오세훈", "010-0000-7680", "110444455556", "deposit", m(40), m(-7), "waiting", None, None),  # 너무 일찍 -> 일반
        ("강다은", "010-0000-1160", "3021111222233", "loan", None, m(-6), "waiting", None, None),
        ("윤태양", "010-0000-4084", "3022222333344", "loan", m(3), m(-3), "waiting", None, None),     # 예약 우선
        ("송민아", "010-0000-2891", "110666677778", "fx", None, m(-5), "waiting", None, None),
        ("임재현", "010-0000-9216", "110777788889", "fx", m(-20), m(-4), "waiting", None, None),      # 늦음 -> 일반
        ("배서연", "010-0000-3780", "110888899990", "deposit", m(25), None, "reserved", None, None),
        ("조현우", "010-0000-6713", "3023333444455", "loan", m(60), None, "reserved", None, None),
        ("신유나", "010-0000-8583", "110999900001", "fx", m(-30), None, "noshow", None, None),
    ]
    for i, (name, phone, acc, svc, res, arr, status, win, called) in enumerate(rows):
        no = issue_number(svc, arr) if arr else None
        db.execute(
            "INSERT INTO tickets(ticket_no,service,name,phone,account,source,reservation_code,reserved_at,"
            "arrived_at,status,window,called_at,ended_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, svc, name, phone, acc, "reservation" if res else "walkin",
             f"DEMO{i:02d}" if res else None, iso(res), iso(arr), status, win, iso(called),
             iso(m(-20)) if status in ("done", "hold") else None),
        )
        db.commit()
