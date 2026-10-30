"""간단 검증 (임시 DB 사용): python test_api.py"""
import tempfile
from pathlib import Path

import app as A

A.DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
A.init_db()
from fastapi.testclient import TestClient

c = TestClient(A.app)
s = c.get("/api/schedule").json()
assert len(s["rooms"]) == 3 and len(s["users"]) == 5
print("minutes", s["minutes"], "bookings", len(s["bookings"]))


def post(**k):
    d = dict(user_id=1, room_id=3, start_slot=17, end_slot=18, title="x")
    d.update(k)
    return c.post("/api/bookings", json=d)


if s["minutes"] < 17 * 30:
    r = post()
    assert r.status_code == 201, r.text
    bid = r.json()["booking_id"]
    assert post().status_code == 409                                   # R-02
    assert post(title="").status_code == 400                           # R-05
    assert post(title="가" * 31).status_code == 400
    assert post(start_slot=-1).status_code == 400                      # R-01
    assert post(end_slot=19).status_code == 400
    assert post(room_id=1, start_slot=9, end_slot=18).status_code == 400  # R-03
    assert c.post(f"/api/bookings/{bid}/cancel", json={"user_id": 2}).status_code == 403  # R-06
    assert c.post(f"/api/bookings/{bid}/cancel", json={"user_id": 1}).status_code == 200
    assert post().status_code == 201                                   # R-08
else:
    print("(17:30 이후라 일부 생략)")
assert post(start_slot=0, end_slot=1, room_id=1).status_code in (400, 409)  # R-04
# R-07: 이미 시작한 시드 예약은 취소 불가
for b in s["bookings"]:
    if b["start_slot"] * 30 < s["minutes"]:
        assert c.post(f"/api/bookings/{b['booking_id']}/cancel",
                      json={"user_id": b["user_id"]}).status_code == 400
print("OK")
