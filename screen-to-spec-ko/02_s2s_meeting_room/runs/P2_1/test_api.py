"""Phase 1 API 검증. 실행: python test_api.py"""
import os
import sqlite3
import tempfile
from datetime import datetime

tmp = tempfile.mkdtemp()
os.environ["MR_DB_PATH"] = os.path.join(tmp, "t.db")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FIXED = {"now": datetime(2026, 10, 30, 10, 0, 0)}
main.now_kst = lambda: FIXED["now"]
c = TestClient(main.app)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    assert cond, name


def post(room, user, slot):
    return c.post("/api/reservations", json={"room_id": room, "user_id": user, "slot_start": slot})


# T-03 시드
check("T-03 rooms 3", len(c.get("/api/rooms").json()) == 3)
check("T-03 users 8", len(c.get("/api/users").json()) == 8)
main.init_db()
check("T-03 reseed no dup", len(c.get("/api/users").json()) == 8)
# T-22 빈 목록
check("T-22 empty list", c.get("/api/reservations").json() == [])
check("list other date 400", c.get("/api/reservations?date=2026-10-31").status_code == 400)
# T-05 / T-25 / T-26
r = post(1, 1, "10:30")
check("T-05 create 201", r.status_code == 201)
check("T-25 adjacent ok", post(1, 1, "11:00").status_code == 201)
check("T-25 same user other room ok", post(2, 1, "10:30").status_code == 201)
check("T-26 slot == now -> 422", post(1, 1, "10:00").status_code == 422)
check("T-07 past message", post(1, 1, "09:00").json()["detail"] == "이미 지난 시간은 예약할 수 없습니다.")
# T-08
r = post(1, 2, "10:30")
check("T-08 conflict 409", r.status_code == 409 and r.json()["detail"] == "이미 다른 사람이 예약한 시간입니다.")
# T-27
check("T-27 08:30 400", post(1, 1, "08:30").status_code == 400)
check("T-27 18:00 400", post(1, 1, "18:00").status_code == 400)
check("T-27 10:15 400", post(1, 1, "10:15").status_code == 400)
check("T-27 bad room 404", post(99, 1, "12:00").status_code == 404)
check("T-27 bad user 404", post(1, 99, "12:00").status_code == 404)
check("17:30 allowed", post(3, 1, "17:30").status_code == 201)
lst = c.get("/api/reservations").json()
check("list has names", all("user_name" in x for x in lst) and len(lst) == 4)
# T-11
rid = [x for x in lst if x["room_id"] == 1 and x["slot_start"] == "10:30"][0]["id"]
r = c.delete(f"/api/reservations/{rid}?user_id=2")
check("T-11 other user 403", r.status_code == 403 and r.json()["detail"] == "본인이 만든 예약만 취소할 수 있습니다.")
# T-10 / T-13 / T-28
check("T-10 cancel 200", c.delete(f"/api/reservations/{rid}?user_id=1").status_code == 200)
check("T-28 re-cancel 409", c.delete(f"/api/reservations/{rid}?user_id=1").status_code == 409)
check("T-28 missing 404", c.delete("/api/reservations/9999?user_id=1").status_code == 404)
check("T-13 rebook ok", post(1, 2, "10:30").status_code == 201)
db = sqlite3.connect(os.environ["MR_DB_PATH"])
check("T-13 cancelled row kept", db.execute("SELECT COUNT(*) FROM mr_reservations WHERE status='cancelled'").fetchone()[0] == 1)
# T-12 시작한 예약 취소 불가
FIXED["now"] = datetime(2026, 10, 30, 11, 0, 0)
rid2 = [x for x in c.get("/api/reservations").json() if x["slot_start"] == "11:00"][0]["id"]
r = c.delete(f"/api/reservations/{rid2}?user_id=1")
check("T-12 started -> 422", r.status_code == 422 and r.json()["detail"] == "이미 시작했거나 지난 예약은 취소할 수 없습니다.")
# T-14 / T-29
names = [n for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
check("T-14 mr_ prefix", all(n.startswith("mr_") for n in names))
check("T-29 no write APIs", c.post("/api/rooms", json={}).status_code == 405
      and c.post("/api/users", json={}).status_code == 405
      and c.delete("/api/rooms/1").status_code in (404, 405))
check("detail 400 json", c.post("/api/reservations", json={}).json() == {"detail": "잘못된 요청입니다."})
print("ALL PASS")
