import os, sys, tempfile
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MR_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import main
from fastapi.testclient import TestClient

c = TestClient(main.app)
main.now = lambda: datetime(2026, 10, 30, 10, 0, 0, tzinfo=main.KST)
T = "2026-10-30"

def post(**kw):
    return c.post("/api/bookings", json=kw)

def check(r, code, detail=None):
    assert r.status_code == code, (r.status_code, r.text)
    if detail: assert r.json()["detail"] == detail, r.text

def test_all():
    assert len(c.get("/api/rooms").json()) == 3 and len(c.get("/api/users").json()) == 5
    main.init_db(); assert len(c.get("/api/rooms").json()) == 3
    assert len(c.get(f"/api/schedule?date={T}").json()) == 3
    check(c.get("/api/schedule?date=2026-10-31"), 400, "오늘 날짜만 조회·예약할 수 있습니다")
    check(post(room_id=1, slot_start="10:00", user_id=1), 400, "이미 지난 시간은 예약할 수 없습니다")
    r = post(room_id=1, slot_start="10:30", user_id=1); check(r, 201); bid = r.json()["id"]
    check(post(room_id=1, slot_start="10:30", user_id=2), 409, "이미 예약된 시간입니다")
    check(post(room_id=1, slot_start="11:00", user_id=2), 201)       # 인접
    check(post(room_id=2, slot_start="10:30", user_id=1), 201)       # 다른 방 같은 사람
    check(post(room_id=1, slot_start="10:30", user_id=1, booking_date="2026-10-31"), 400, "오늘 날짜만 조회·예약할 수 있습니다")
    check(post(room_id=1, slot_start="09:15", user_id=1), 400, "예약할 수 없는 시간입니다")
    check(post(room_id=1, slot_start="18:00", user_id=1), 400, "예약할 수 없는 시간입니다")
    check(post(room_id=9, slot_start="11:30", user_id=1), 404, "존재하지 않는 회의실입니다")
    check(post(room_id=1, slot_start="11:30", user_id=99), 400, "사용자를 선택해 주세요")
    check(post(room_id=1, slot_start="11:30"), 400, "사용자를 선택해 주세요")
    check(c.delete(f"/api/bookings/{bid}?user_id=2"), 403, "본인 예약만 취소할 수 있습니다")
    check(c.delete("/api/bookings/999?user_id=1"), 404, "예약을 찾을 수 없습니다")
    check(c.delete("/api/bookings/1?user_id=1"), 400, "이미 시작된 예약은 취소할 수 없습니다")
    check(c.delete(f"/api/bookings/{bid}?user_id=1"), 200)
    check(c.delete(f"/api/bookings/{bid}?user_id=1"), 409, "이미 취소된 예약입니다")
    check(post(room_id=1, slot_start="10:30", user_id=3), 201)       # 재예약
    row = main.connect().execute("SELECT status,cancelled_at FROM mr_bookings WHERE id=?", (bid,)).fetchone()
    assert row[0] == "CANCELLED" and row[1]

def test_unique_index_race():
    # 사전 확인을 우회해 DB 유니크 위반이 409로 변환되는지
    orig = main.connect
    class C:
        def __init__(s): s.c = orig()
        def execute(s, sql, *a):
            if sql.startswith("SELECT 1 FROM mr_bookings"):
                return s.c.execute("SELECT NULL WHERE 0")
            return s.c.execute(sql, *a)
        def __enter__(s): return s.c.__enter__()
        def __exit__(s, *a): return s.c.__exit__(*a)
        def close(s): s.c.close()
    main.connect = lambda: C()
    try:
        check(post(room_id=3, slot_start="15:00", user_id=1), 201)
        check(post(room_id=3, slot_start="15:00", user_id=2), 409, "이미 예약된 시간입니다")
    finally:
        main.connect = orig
