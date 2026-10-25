"""가상 데이터. DB 가 비어 있을 때만 main 이 호출한다. (python -m app.seed --reset 으로 초기화)"""
import sys
from datetime import datetime, timedelta

from . import billing
from .db import DB_PATH, connect, hash_pw, init_db

USERS = [  # username, password, name, role
    ("staff1", "staff1234", "김점검 (직원)", "staff"),
    ("staff2", "staff1234", "이반납 (직원)", "staff"),
    ("hong", "cust1234", "홍길동", "customer"),
    ("kim", "cust1234", "김영희", "customer"),
    ("park", "cust1234", "박철수", "customer"),
]
VEHICLES = [  # plate, model, daily_rate, tank_l
    ("12가3456", "현대 아반떼", 60_000, 47),
    ("34나7890", "기아 K5", 80_000, 60),
    ("56다1234", "현대 쏘나타", 85_000, 60),
    ("78라5678", "기아 쏘렌토", 120_000, 67),
    ("90마9012", "현대 캐스퍼", 45_000, 35),
    ("21바3344", "제네시스 G80", 200_000, 70),
]


def run():
    init_db()
    now = datetime.now().replace(second=0, microsecond=0)
    f = lambda d: d.isoformat(timespec="minutes")
    c = connect()
    c.execute("BEGIN")
    uid = {}
    for u, p, n, r in USERS:
        uid[u] = c.execute("INSERT INTO users(username,password_hash,name,role) VALUES(?,?,?,?)",
                           (u, hash_pw(p), n, r)).lastrowid
    vid = [c.execute("INSERT INTO vehicles(plate,model,daily_rate,tank_l) VALUES(?,?,?,?)", v).lastrowid
           for v in VEHICLES]

    def rental(cust, veh, start, due, odo, fuel, pre=()):
        rid = c.execute("INSERT INTO rentals(customer_id,vehicle_id,start_at,due_at,start_odometer,start_fuel)"
                        " VALUES(?,?,?,?,?,?)", (uid[cust], vid[veh], f(start), f(due), odo, fuel)).lastrowid
        for part, grade in pre:
            c.execute("INSERT INTO damages(rental_id,kind,part,grade) VALUES(?,'pre',?,?)", (rid, part, grade))
        return rid

    # 진행 중 4건 — 지연 / 정시 / 기존 흠집 다수 / 반납 예정 여유
    rental("hong", 0, now - timedelta(days=3, hours=1), now - timedelta(hours=3), 25_300, 8,
           pre=[("앞 범퍼", 1), ("운전석 앞문", 2)])
    rental("kim", 1, now - timedelta(days=2), now + timedelta(hours=2), 41_870, 6,
           pre=[("뒤 범퍼", 2), ("지붕", 1), ("조수석 뒷문", 1)])
    rental("park", 3, now - timedelta(days=1), now + timedelta(days=2), 12_040, 8)
    rental("hong", 5, now - timedelta(hours=5), now + timedelta(days=1), 3_210, 7, pre=[("본넷", 1)])

    # 반납 완료 1건 (고객 청구 내역 화면용): 연료 부족 + 기존 흠집 제외 + 신규 흠집
    start, due = now - timedelta(days=9), now - timedelta(days=6)
    rid = rental("hong", 2, start, due, 30_000, 8, pre=[("좌측 앞 펜더", 1)])
    lines = [billing.fuel_line(8, 4, 60)] + billing.damage_lines(
        [{"part": "좌측 앞 펜더", "grade": 1}, {"part": "트렁크", "grade": 2}], [{"part": "좌측 앞 펜더", "grade": 1}])
    lines = [l for l in lines if l]
    total = sum(l["amount"] for l in lines)
    c.execute("UPDATE rentals SET status='returned', returned_at=?, ret_odometer=?, ret_fuel=4, inspected_by=?, total=?"
              " WHERE id=?", (f(due), 30_820, uid["staff1"], total, rid))
    for l in lines:
        did = None
        if l["type"] == "damage":
            did = c.execute("INSERT INTO damages(rental_id,kind,part,grade,note) VALUES(?,'return',?,?,?)",
                            (rid, l["part"], l["grade"], l["note"])).lastrowid
        c.execute("INSERT INTO charges(rental_id,type,description,amount,damage_id) VALUES(?,?,?,?,?)",
                  (rid, l["type"], l["description"], l["amount"], did))
    c.execute("COMMIT")
    c.close()


def seed_if_empty():
    init_db()
    c = connect()
    empty = c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    c.close()
    if empty:
        run()


if __name__ == "__main__":
    if "--reset" in sys.argv and DB_PATH.exists():
        DB_PATH.unlink()
    seed_if_empty()
    print("seeded:", DB_PATH)
