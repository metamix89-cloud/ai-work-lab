"""가상 데이터. DB 가 비어 있을 때만 1회 삽입."""
import os
import struct
import uuid
import zlib
from datetime import timedelta

from . import calc, db
from .security import hash_password

DEMO_PASSWORD = "demo1234"


def _png(rgb: tuple[int, int, int], w=320, h=200) -> bytes:
    row = b"\x00" + bytes(rgb) * w
    raw = zlib.compress(row * h)

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def seed_if_empty():
    from .main import iso, now
    with db.connect() as con:
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        pw = hash_password(DEMO_PASSWORD)
        users = [("staff1", "정직원", "staff"), ("staff2", "한점검", "staff"),
                 ("minjun", "김민준", "customer"), ("seoyeon", "이서연", "customer"),
                 ("jihun", "박지훈", "customer")]
        ids = {}
        for u, n, role in users:
            ids[u] = con.execute("INSERT INTO users(username,password_hash,name,role) VALUES(?,?,?,?)",
                                 (u, pw, n, role)).lastrowid
        veh = {}
        for key, plate, model, rate, tank, odo in [
            ("avante", "12가 3456", "아반떼 CN7", 60_000, 47, 31_200),
            ("sonata", "34나 7788", "쏘나타 DN8", 80_000, 60, 18_450),
            ("carnival", "56다 1020", "카니발 KA4", 130_000, 72, 52_900),
            ("genesis", "78라 9911", "제네시스 G80", 200_000, 70, 9_800),
            ("ray", "90마 4321", "레이", 45_000, 35, 64_300)]:
            veh[key] = con.execute("INSERT INTO vehicles(plate,model,daily_rate,tank_liters,odometer) "
                                   "VALUES(?,?,?,?,?)", (plate, model, rate, tank, odo)).lastrowid

        def photo(rental_id, color, uploader):
            name = uuid.uuid4().hex
            with open(os.path.join(db.UPLOAD_DIR, name), "wb") as f:
                f.write(_png(color))
            return con.execute("INSERT INTO photos(rental_id,filename,content_type,uploaded_by) "
                               "VALUES(?,?,?,?)", (rental_id, name, "image/png", uploader)).lastrowid

        def rental(cust, v, start, due, fuel, odo, pickup):
            rid = con.execute(
                "INSERT INTO rentals(customer_id,vehicle_id,start_at,due_at,start_fuel,start_odo) "
                "VALUES(?,?,?,?,?,?)", (ids[cust], veh[v], iso(start), iso(due), fuel, odo)).lastrowid
            for part, grade, note in pickup:
                con.execute("INSERT INTO damages(rental_id,phase,part,grade,note) VALUES(?,?,?,?,?)",
                            (rid, "pickup", part, grade, note))
            return rid

        t = now()
        # 1) 정시 반납 예정 — 대여 전 흠집 2건 (앞 범퍼 경미, 앞 우측 도어 보통)
        rental("minjun", "avante", t - timedelta(days=2), t + timedelta(hours=3), 8, 31_200,
               [("front_bumper", 1, "좌측 하단 스크래치"), ("door_fr", 2, "문콕 자국 3cm")])
        # 2) 5시간 지연 중
        rental("seoyeon", "sonata", t - timedelta(days=3, hours=1), t - timedelta(hours=5), 6, 18_450,
               [("rear_bumper", 1, "긁힘")])
        # 3) 내일 반납
        rental("minjun", "carnival", t - timedelta(days=1), t + timedelta(days=1), 8, 52_900, [])
        # 4) 다른 고객(접근 분리 확인용)
        rental("jihun", "genesis", t - timedelta(hours=20), t + timedelta(hours=28), 7, 9_800,
               [("wheel", 1, "휠 가장자리 스크래치")])

        # 5) 이미 반납·청구 완료된 과거 건 (이서연)
        start, due = t - timedelta(days=9), t - timedelta(days=6)
        rid = rental("seoyeon", "ray", start, due, 8, 63_900,
                     [("hood", 1, "비산 자국"), ("mirror", 1, "")])
        ret = due + timedelta(hours=2, minutes=10)
        found = [{"part": "hood", "grade": 1}, {"part": "door_rl", "grade": 2}]
        res = calc.compute(daily_rate=45_000, tank_liters=35, due_at=due, start_fuel=8, returned_at=ret,
                           return_fuel=5, pickup_damages=[{"part": "hood", "grade": 1},
                                                          {"part": "mirror", "grade": 1}],
                           found_damages=found)
        staff = ids["staff1"]
        con.execute("UPDATE rentals SET status='returned',returned_at=?,return_fuel=5,return_odo=64300,"
                    "staff_id=? WHERE id=?", (iso(ret), staff, rid))
        for it in res["damage_items"]:
            pid = photo(rid, (200, 90, 60), staff) if it["fee"] else None
            con.execute("INSERT INTO damages(rental_id,phase,part,grade,note,photo_id,status,prior_grade,fee) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (rid, "return", it["part"], it["grade"],
                         "뒤 좌측 도어 찍힘" if it["fee"] else "대여 전 기록과 동일", pid,
                         it["status"], it["prior_grade"], it["fee"]))
        con.execute("INSERT INTO invoices(rental_id,late_minutes,late_fee,fuel_short_units,fuel_fee,"
                    "damage_fee,total,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (rid, res["late_minutes"], res["late_fee"], res["fuel_short_units"], res["fuel_fee"],
                     res["damage_fee"], res["total"], iso(ret)))
        con.commit()
