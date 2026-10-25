"""가상 데이터. DB가 비어 있을 때 최초 1회 실행."""
import secrets
import struct
import zlib
from datetime import datetime, timedelta

import billing
from main import UPLOAD_DIR, hash_pw

USERS = [  # username, 이름, 역할, 비밀번호
    ("staff", "정직원", "staff", "staff1234"),
    ("kim", "김민수", "customer", "kim1234"),
    ("lee", "이서연", "customer", "lee1234"),
    ("park", "박지훈", "customer", "park1234"),
]
VEHICLES = [("12가3456", "현대 아반떼"), ("34나7890", "현대 쏘나타"), ("56다1234", "기아 카니발"),
            ("78라5678", "기아 K5"), ("90마2468", "현대 투싼")]


def make_png(rgb: tuple[int, int, int], size: int = 96) -> bytes:
    row = b"\x00" + bytes(rgb) * size
    raw = zlib.compress(row * size)

    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def run(con):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ids = {}
    for username, name, role, pw in USERS:
        salt = secrets.token_hex(16)
        cur = con.execute("INSERT INTO users(username,name,role,salt,pw_hash) VALUES(?,?,?,?,?)",
                          (username, name, role, salt, hash_pw(pw, salt)))
        ids[username] = cur.lastrowid
    vid = [con.execute("INSERT INTO vehicles(plate,model) VALUES(?,?)", v).lastrowid for v in VEHICLES]

    shade = iter([(200, 90, 80), (90, 140, 200), (120, 180, 110), (210, 170, 70), (150, 110, 190), (100, 100, 100)])

    def add_damage(rental_id, phase, part, grade, **kw):
        name = f"{secrets.token_hex(16)}.png"
        (UPLOAD_DIR / name).write_bytes(make_png(next(shade)))
        return con.execute(
            "INSERT INTO damages(rental_id,phase,part,grade,photo,pre_existing,matched_pickup_id,charge,note) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (rental_id, phase, part, grade, name, kw.get("pre", 0), kw.get("match"), kw.get("charge", 0),
             kw.get("note"))).lastrowid

    def rental(cust, veh, pickup, due, fuel, odo):
        f = lambda d: d.isoformat(timespec="minutes")
        return con.execute(
            "INSERT INTO rentals(customer_id,vehicle_id,pickup_at,due_at,pickup_fuel,pickup_odometer) VALUES(?,?,?,?,?,?)",
            (ids[cust], vid[veh], f(pickup), f(due), fuel, odo)).lastrowid

    now = datetime.now().replace(second=0, microsecond=0)
    h = lambda n: timedelta(hours=n)

    # 진행 중인 대여 3건
    r1 = rental("kim", 0, now - h(72), now - h(1), 8, 12000)       # 1시간 늦음 예정
    add_damage(r1, "pickup", "front_bumper", "minor")
    add_damage(r1, "pickup", "front_left_door", "major")
    r2 = rental("lee", 1, now - h(48), now + h(3), 6, 30500)
    add_damage(r2, "pickup", "rear_bumper", "minor")
    rental("park", 2, now - h(24), now - h(2), 7, 8800)

    # 이미 반납·청구가 끝난 과거 대여 (실제 계산 함수로 생성)
    p = now - timedelta(days=20)
    r4 = rental("kim", 3, p, p + h(48), 8, 5000)
    pre = add_damage(r4, "pickup", "hood", "minor")
    pickup_d = [{"id": pre, "part": "hood", "grade": "minor"}]
    ret_dt = p + h(48) + timedelta(minutes=95)
    ret = [{"part": "hood", "grade": "minor"}, {"part": "rear_bumper", "grade": "major"}]
    bill = billing.compute_bill(p + h(48), ret_dt, 8, 5, pickup_d, ret)
    con.execute("UPDATE rentals SET status='returned', returned_at=?, return_fuel=5, return_odometer=5620 WHERE id=?",
                (ret_dt.isoformat(timespec="minutes"), r4))
    for d in bill.damages:
        add_damage(r4, "return", d.part, d.grade, pre=int(d.pre_existing), match=d.matched_pickup_id,
                   charge=d.charge, note=d.note)
    con.execute("INSERT INTO charges VALUES(?,?,?,?,?,?,?,?)",
                (r4, bill.late_minutes, bill.late_fee, bill.fuel_short, bill.fuel_fee, bill.damage_fee,
                 bill.total, now.isoformat(timespec="seconds")))
