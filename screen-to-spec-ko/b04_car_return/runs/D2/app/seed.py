"""가상 데이터. 데이터가 하나도 없을 때만 채운다. 이미 반납된 건도 실제 반납 로직으로 계산해 넣는다."""
from datetime import timedelta

from . import photos, service
from .auth import hash_password
from .db import connect

USERS = [  # username, name, role, password
    ("staff", "최직원", "staff", "staff1234"),
    ("kim", "김민준", "customer", "kim1234"),
    ("lee", "이서연", "customer", "lee1234"),
    ("park", "박지호", "customer", "park1234"),
]
VEHICLES = [("12가3456", "현대 아반떼"), ("34나5678", "기아 K5"), ("56다7890", "현대 쏘나타"),
            ("78라1234", "기아 쏘렌토"), ("90마5678", "제네시스 G80"), ("11바2222", "현대 캐스퍼")]

COLORS = {"minor": (230, 200, 90), "major": (230, 140, 60), "severe": (200, 60, 60)}


def _photo(grade: str) -> str:
    return photos.save(photos.placeholder_png(COLORS[grade]))


def seed_if_empty() -> None:
    conn = connect()
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        uid = {}
        for username, name, role, pw in USERS:
            uid[username] = conn.execute("INSERT INTO users(username,name,role,pw_hash) VALUES(?,?,?,?)",
                                         (username, name, role, hash_password(pw))).lastrowid
        vid = [conn.execute("INSERT INTO vehicles(plate,model) VALUES(?,?)", v).lastrowid for v in VEHICLES]
        now = service.now_kst().replace(second=0, microsecond=0)

        def rental(cust, veh, start_ago_h, due_delta_min, fuel, odo, pickup=()):
            rid = conn.execute(
                "INSERT INTO rentals(customer_id,vehicle_id,started_at,due_at,start_fuel,start_odometer)"
                " VALUES(?,?,?,?,?,?)",
                (uid[cust], vid[veh], (now - timedelta(hours=start_ago_h)).isoformat(),
                 (now + timedelta(minutes=due_delta_min)).isoformat(), fuel, odo)).lastrowid
            for part, grade, note in pickup:  # 대여 전부터 있던 흠집 (기록만, 0원)
                conn.execute("INSERT INTO damages(rental_id,phase,part,grade,photo,note,pre_existing,fee)"
                             " VALUES(?,?,?,?,?,?,1,0)", (rid, "pickup", part, grade, _photo(grade), note))
            return rid

        # 반납 대기 — 반납 시각을 '지금'으로 넣었을 때 각 요금 구간을 확인할 수 있게 구성
        rental("kim", 0, 30, -20, 8, 20_000, [("left_front_door", "minor", "문콕 자국")])       # 유예 이내
        rental("kim", 1, 30, -100, 6, 45_000)                                                    # 지연 2블록
        rental("lee", 2, 80, -600, 7, 31_000,
               [("front_bumper", "major", "긁힘+찌그러짐"), ("hood", "minor", "도장 벗겨짐")])      # 상한 80,000
        rental("lee", 3, 24, 180, 5, 12_000)                                                     # 일찍 반납
        rental("park", 4, 26, -31, 8, 8_000)                                                     # 31분 → 10,000

        # 이미 반납 완료된 건 (고객 화면의 청구 내역용)
        hist = rental("park", 5, 120, -60 * 72, 8, 3_000, [("rear_bumper", "minor", "잔기스")])
        pre = conn.execute("SELECT id FROM damages WHERE rental_id=?", (hist,)).fetchone()[0]
        service.finalize_return(conn, hist, uid["staff"], now - timedelta(hours=72) + timedelta(minutes=45), 5, 3_450,
                                [{"part": "rear_bumper", "grade": "minor", "photo": _photo("minor"), "pre_existing_id": pre},
                                 {"part": "right_rear_door", "grade": "major", "photo": _photo("major"),
                                  "note": "주차 중 접촉", "pre_existing_id": None}])
        ok = rental("kim", 2, 200, -60 * 150, 8, 28_000)
        service.finalize_return(conn, ok, uid["staff"], now - timedelta(hours=150) - timedelta(minutes=10), 8, 28_400, [])
    finally:
        conn.close()
