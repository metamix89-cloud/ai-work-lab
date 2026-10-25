import os
import tempfile
from datetime import datetime, timedelta

os.environ["RENTAL_DATA_DIR"] = tempfile.mkdtemp()

import pytest
from fastapi.testclient import TestClient

from app import calc
from app.main import app, iso, now
from app.seed import DEMO_PASSWORD, _png

D = datetime(2026, 1, 1, 12, 0)


def test_late_fee():
    assert calc.late_fee(D, D + timedelta(minutes=30), 60000)[0] == 0          # 유예 이내
    assert calc.late_fee(D, D + timedelta(minutes=31), 60000)[0] == 6000       # 1시간 올림
    assert calc.late_fee(D, D + timedelta(hours=5), 60000)[0] == 30000
    assert calc.late_fee(D, D + timedelta(hours=12), 60000)[0] == 60000        # 일 대여료 상한
    assert calc.late_fee(D, D + timedelta(hours=26), 60000)[0] == 60000 + 12000


def test_fuel_fee():
    assert calc.fuel_fee(8, 8, 48)[0] == 0
    assert calc.fuel_fee(6, 8, 48)[0] == 0                                     # 더 채워도 환급 없음
    assert calc.fuel_fee(8, 5, 48) == (54000, 3)                               # 3칸 = 18L x 3000


def test_preexisting_damage_not_billed():
    pickup = [{"part": "front_bumper", "grade": 2}, {"part": "hood", "grade": 1}]
    items = calc.damage_items(pickup, [
        {"part": "front_bumper", "grade": 2}, {"part": "hood", "grade": 3},
        {"part": "roof", "grade": 1}, {"part": "wheel", "grade": 1}])
    by = {i["part"]: i for i in items}
    assert by["front_bumper"]["fee"] == 0 and by["front_bumper"]["status"] == "pre_existing"
    assert by["hood"]["fee"] == 400000 - 50000 and by["hood"]["status"] == "worsened"
    assert by["roof"]["fee"] == calc.damage_fee("roof", 1)
    assert by["wheel"]["status"] == "new"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, user):
    c = TestClient(app)
    assert c.post("/api/login", json={"username": user, "password": DEMO_PASSWORD}).status_code == 200
    return c


def test_customer_isolation(client):
    staff, minjun, seoyeon = login(client, "staff1"), login(client, "minjun"), login(client, "seoyeon")
    mine = {r["id"] for r in minjun.get("/api/rentals").json()}
    theirs = {r["id"] for r in seoyeon.get("/api/rentals").json()}
    assert mine and theirs and not (mine & theirs)
    other = next(iter(theirs))
    assert minjun.get(f"/api/rentals/{other}").status_code == 404
    assert minjun.post(f"/api/rentals/{other}/preview", json={"return_fuel": 8, "return_odo": 99999}).status_code == 403
    assert len(staff.get("/api/rentals").json()) >= len(mine | theirs)
    assert TestClient(app).get("/api/rentals").status_code == 401
    # 사진도 본인 건만
    inv = next(r for r in seoyeon.get("/api/rentals?status=returned").json())
    pid = next(d["photo_id"] for d in inv["return_damages"] if d["photo_id"])
    assert seoyeon.get(f"/api/photos/{pid}").status_code == 200
    assert minjun.get(f"/api/photos/{pid}").status_code == 404


def test_return_flow_end_to_end(client):
    staff, minjun = login(client, "staff1"), login(client, "minjun")
    r = next(x for x in staff.get("/api/rentals?status=rented").json() if x["customer_name"] == "김민준" and x["model"].startswith("아반떼"))
    rid = r["id"]
    assert {d["part"] for d in r["pickup_damages"]} == {"front_bumper", "door_fr"}

    up = staff.post(f"/api/rentals/{rid}/photos", files={"file": ("x.png", _png((1, 2, 3)), "image/png")})
    assert up.status_code == 200
    bad = staff.post(f"/api/rentals/{rid}/photos", files={"file": ("x.png", b"<script>alert(1)</script>", "image/png")})
    assert bad.status_code == 400

    body = {"returned_at": iso(now()), "return_fuel": 6, "return_odo": r["start_odo"] + 300,
            "damages": [{"part": "front_bumper", "grade": 1},               # 기존과 동일 -> 0원
                        {"part": "door_fr", "grade": 2},                    # 기존과 동일 -> 0원
                        {"part": "rear_bumper", "grade": 2, "photo_id": up.json()["photo_id"]}]}
    pre = staff.post(f"/api/rentals/{rid}/preview", json=body).json()
    assert pre["late_fee"] == 0
    assert pre["fuel_fee"] == calc.fuel_fee(8, 6, 47)[0]
    assert pre["damage_fee"] == calc.damage_fee("rear_bumper", 2)

    # 청구되는 흠집인데 사진 없음 -> 거부
    nophoto = {**body, "damages": [{"part": "roof", "grade": 1}]}
    assert staff.post(f"/api/rentals/{rid}/return", json=nophoto).status_code == 400
    # 주행거리 역행 / 중복 부위 거부
    assert staff.post(f"/api/rentals/{rid}/return", json={**body, "return_odo": 1}).status_code == 400
    dup = {**body, "damages": [{"part": "hood", "grade": 1}, {"part": "hood", "grade": 2}]}
    assert staff.post(f"/api/rentals/{rid}/return", json=dup).status_code == 400

    done = staff.post(f"/api/rentals/{rid}/return", json=body)
    assert done.status_code == 200 and done.json()["invoice"]["total"] == pre["total"]
    assert staff.post(f"/api/rentals/{rid}/return", json=body).status_code == 409   # 이중 청구 방지

    mine = minjun.get(f"/api/rentals/{rid}").json()
    assert mine["invoice"]["total"] == pre["total"]
    st = {d["part"]: d["status"] for d in mine["return_damages"]}
    assert st == {"front_bumper": "pre_existing", "door_fr": "pre_existing", "rear_bumper": "new"}
