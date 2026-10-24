"""가상 데이터. DB가 없으면 현재 시각 기준 상대 날짜로 생성한다. (python seed.py --reset 으로 초기화)"""
import sqlite3
import sys
from datetime import timedelta

from main import DB_PATH, SCHEMA, iso, now

TRAINERS = ["박코치", "이코치", "최코치"]
TITLES = {"박코치": "1:1 PT", "이코치": "1:1 PT", "최코치": "소그룹 PT"}


def ensure_db(reset=False):
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    if DB_PATH.exists():
        return
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    n = now()
    base = n.replace(minute=0, second=0)

    def cls(start, trainer, cap):
        return con.execute("INSERT INTO classes(trainer,title,start_at,capacity) VALUES(?,?,?,?)",
                           (trainer, TITLES[trainer], iso(start), cap)).lastrowid

    # 지난 10일 ~ 앞으로 6일, 하루 4타임
    past = []
    for d in range(-10, 7):
        day = base.replace(hour=0) + timedelta(days=d)
        for i, h in enumerate((10, 14, 19, 20)):
            t = TRAINERS[(d + i) % 3]
            cap = 3 if t == "최코치" else (2 if i == 3 else 1)
            start = day.replace(hour=h)
            cid = cls(start, t, cap)
            if start < n - timedelta(hours=6):
                past.append((cid, cap))
    usage = {cid: 0 for cid, _ in past}

    members = {}
    for name, phone in [("김민수", "010-0000-5504"), ("이서연", "010-0000-8029"), ("박지훈", "010-0000-7613"),
                        ("최유진", "010-0000-5732"), ("정하늘", "010-0000-5003"), ("강도윤", "010-0000-9641"),
                        ("윤서아", "010-0000-1875"), ("한지우", "010-0000-3165")]:
        members[name] = con.execute("INSERT INTO members(name,phone) VALUES(?,?)", (name, phone)).lastrowid

    def membership(name, mname, total, start_days, end_days, attended=0, noshow=0):
        mid = con.execute("INSERT INTO memberships(member_id,name,total,remaining,starts_at,expires_at) VALUES(?,?,?,?,?,?)",
                          (members[name], mname, total, total, iso(n + timedelta(days=start_days)),
                           iso(n + timedelta(days=end_days)))).lastrowid
        con.execute("INSERT INTO ledger(membership_id,delta,reason,at) VALUES(?,?,?,?)",
                    (mid, total, "회원권 등록", iso(n + timedelta(days=start_days))))
        history = ["attended"] * attended + ["noshow"] * noshow
        for st in history:
            cid = next(c for c, cap in past if usage[c] < cap and not con.execute(
                "SELECT 1 FROM bookings WHERE class_id=? AND member_id=?", (c, members[name])).fetchone())
            usage[cid] += 1
            bid = con.execute("INSERT INTO bookings(class_id,member_id,membership_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                              (cid, members[name], mid, st, iso(n - timedelta(days=12)), iso(n - timedelta(days=5)))).lastrowid
            con.execute("UPDATE memberships SET remaining=remaining-1 WHERE id=?", (mid,))
            con.execute("INSERT INTO ledger(membership_id,booking_id,delta,reason,at) VALUES(?,?,?,?,?)",
                        (mid, bid, -1, "출석 차감" if st == "attended" else "노쇼 차감", iso(n - timedelta(days=5))))
        return mid

    m_kim = membership("김민수", "PT 10회권", 10, -30, 60, attended=3)
    m_lee = membership("이서연", "PT 10회권", 10, -50, 40, attended=9)       # 잔여 1회
    m_park = membership("박지훈", "PT 10회권", 10, -40, 50, attended=4, noshow=3)  # 노쇼 3회 → 차단
    membership("최유진", "PT 10회권", 10, -120, -5, attended=6)               # 만료
    m_jung = membership("정하늘", "PT 20회권", 20, -20, 160, attended=5)
    membership("강도윤", "PT 5회권", 5, -30, 60, attended=5)                  # 소진
    m_yoon = membership("윤서아", "PT 10회권", 10, -25, 65, attended=2, noshow=2)  # 노쇼 2회 (경계)
    m_han = membership("한지우", "PT 5회권", 5, -10, 80)

    until = iso(n + timedelta(days=9))
    con.execute("UPDATE members SET blocked_until=? WHERE id=?", (until, members["박지훈"]))

    def booking(cid, name, mid):
        con.execute("INSERT INTO bookings(class_id,member_id,membership_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (cid, members[name], mid, "booked", iso(n - timedelta(days=1)), iso(n - timedelta(days=1))))

    # 오늘 데모용 수업 (현재 시각 기준 상대)
    booking(cls(base - timedelta(hours=3), "박코치", 1), "김민수", m_kim)            # 출석 처리 연습
    c = cls(base - timedelta(hours=1), "최코치", 3)                                  # 노쇼 처리 → 윤서아 3회 차단 시연
    booking(c, "정하늘", m_jung)
    booking(c, "윤서아", m_yoon)
    booking(cls(base + timedelta(hours=1), "이코치", 1), "한지우", m_han)            # 취소 마감 임박(취소 불가)
    booking(cls(base + timedelta(hours=4), "박코치", 3), "이서연", m_lee)            # 취소 가능
    full = cls(base + timedelta(hours=5), "이코치", 2)                               # 정원 마감
    booking(full, "김민수", m_kim)
    booking(full, "정하늘", m_jung)
    con.commit()
    con.close()


if __name__ == "__main__":
    ensure_db(reset="--reset" in sys.argv)
    print("seeded", DB_PATH)
