"""가상 데이터. DB가 비어 있을 때만 채운다."""
import uuid
from datetime import datetime, timedelta, timezone

import db

# 1x1 PNG 대신 눈에 보이는 작은 SVG 플레이스홀더를 사진으로 사용
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="100%" height="100%" fill="#e8eef5"/>'
       '<path d="M40 150 L120 60 L170 110 L220 40 L290 150Z" fill="#9fb3c8"/>'
       '<text x="160" y="185" font-size="16" text-anchor="middle" fill="#345">{}</text></svg>')

DEMO_PASSWORD = "demo1234"


def _photo(con, staff_id, label):
    name = uuid.uuid4().hex + ".svg"
    (db.UPLOAD_DIR / name).write_text(SVG.format(label), encoding="utf-8")
    cur = con.execute("INSERT INTO photos(filename,mime,uploaded_by,attached) VALUES(?,?,?,1)",
                      (name, "image/svg+xml", staff_id))
    return cur.lastrowid


def run():
    db.init()
    con = db.connect()
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        con.close()
        return
    pw = db.hash_pw(DEMO_PASSWORD)
    users = [("staff1", "박직원", "staff"), ("staff2", "최직원", "staff"),
             ("kim", "김고객", "customer"), ("lee", "이고객", "customer"), ("park", "박고객", "customer")]
    ids = {}
    for u, n, r in users:
        ids[u] = con.execute("INSERT INTO users(username,pw_hash,name,role) VALUES(?,?,?,?)", (u, pw, n, r)).lastrowid
    cars = [("12가3456", "아반떼"), ("34나5678", "쏘나타"), ("56다7890", "K5"), ("78라1234", "투싼"), ("90마5678", "카니발")]
    cid = [con.execute("INSERT INTO cars(plate,model) VALUES(?,?)", c).lastrowid for c in cars]

    now = datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None, second=0, microsecond=0)
    f = lambda d: d.strftime("%Y-%m-%dT%H:%M")
    s = ids["staff1"]

    def rental(cust, car, start, due, fuel, odo, status="active"):
        return con.execute(
            "INSERT INTO rentals(customer_id,car_id,start_at,due_at,start_fuel,start_odometer,status) VALUES(?,?,?,?,?,?,?)",
            (ids[cust], cid[car], f(start), f(due), fuel, odo, status)).lastrowid

    def pre(rid, part, grade):
        con.execute("INSERT INTO rental_damages(rental_id,phase,part,grade,photo_id,pre_existing,fee,note) "
                    "VALUES(?,'checkout',?,?,?,1,0,'')", (rid, part, grade, _photo(con, s, f"{part} {grade}")))

    # 진행 중: 이미 1시간 40분 지연 (유예 초과)
    r1 = rental("kim", 0, now - timedelta(days=3, hours=2), now - timedelta(hours=1, minutes=40), 8, 21500)
    pre(r1, "front_bumper", "minor")
    # 진행 중: 반납 예정이 곧 (정상)
    r2 = rental("lee", 1, now - timedelta(days=1), now + timedelta(hours=3), 6, 40210)
    pre(r2, "door_fl", "major")
    pre(r2, "windshield", "minor")
    # 진행 중: 박고객
    rental("park", 2, now - timedelta(hours=20), now + timedelta(days=1), 7, 15000)
    # 진행 중: 김고객 두 번째 대여 (다른 고객 건과 구분 확인용)
    rental("kim", 4, now - timedelta(hours=5), now + timedelta(hours=19), 8, 5300)

    # 이미 반납 완료된 건 (청구 내역 예시): 20분 지연(유예) + 연료 2칸 + 새 흠집 1건 + 대여 전 흠집 1건(0원)
    st = now - timedelta(days=9)
    due = st + timedelta(days=2)
    r5 = rental("kim", 3, st, due, 8, 30100, "returned")
    pre(r5, "hood", "minor")
    ret = due + timedelta(minutes=20)
    con.execute("INSERT INTO rental_damages(rental_id,phase,part,grade,photo_id,pre_existing,fee,note) VALUES(?,'return','hood','minor',?,1,0,'대여 전부터 있던 흠집')",
                (r5, _photo(con, s, "hood minor (반납 시)")))
    con.execute("INSERT INTO rental_damages(rental_id,phase,part,grade,photo_id,pre_existing,fee,note) VALUES(?,'return','door_rr','major',?,0,150000,'')",
                (r5, _photo(con, s, "door_rr major")))
    con.execute("INSERT INTO returns VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (r5, f(ret), 6, 30650, 20, 0, 2, 30000, 150000, 180000, ids["staff1"]))

    # 반납 완료: 3시간 지연 -> 지연 요금 상한 확인용 (유예 30분 뒤 2.5h -> 3블록)
    st = now - timedelta(days=15)
    due = st + timedelta(days=3)
    r6 = rental("lee", 0, st, due, 5, 12000, "returned")
    ret = due + timedelta(hours=3)
    con.execute("INSERT INTO returns VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (r6, f(ret), 7, 12480, 180, 30000, 0, 0, 0, 30000, ids["staff2"]))
    con.close()


if __name__ == "__main__":
    run()
