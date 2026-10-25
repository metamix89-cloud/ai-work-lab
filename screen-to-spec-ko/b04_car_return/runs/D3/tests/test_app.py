import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["BRR_DB"] = str(Path(_tmp) / "t.db")
os.environ["BRR_UPLOADS"] = str(Path(_tmp) / "up")
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

import pricing
from main import app

D = datetime(2026, 1, 1, 12, 0)
m = lambda n: D + timedelta(minutes=n)


@pytest.mark.parametrize("late_min,fee", [
    (-120, 0), (0, 0), (30, 0),        # 일찍 반납·유예: 환불 없음, 0원
    (31, 10_000), (90, 10_000),        # 31분부터 첫 1시간
    (91, 20_000), (150, 20_000), (151, 30_000),
    (30 + 8 * 60, 80_000), (30 + 8 * 60 + 1, 80_000), (24 * 60, 80_000),  # 상한
])
def test_late_fee(late_min, fee):
    assert pricing.late_fee(D, m(late_min))[1] == fee


def test_late_30m_30s_is_already_31st_minute():
    assert pricing.late_fee(D, D + timedelta(minutes=30, seconds=30))[1] == 10_000


@pytest.mark.parametrize("s,r,fee", [(8, 5, 45_000), (5, 5, 0), (3, 8, 0), (0, 0, 0), (8, 0, 120_000)])
def test_fuel_fee(s, r, fee):
    assert pricing.fuel_fee(s, r)[1] == fee


@pytest.mark.parametrize("bad", [(9, 0), (0, 9), (-1, 0), (0, -1)])
def test_fuel_range(bad):
    with pytest.raises(ValueError):
        pricing.fuel_fee(*bad)


def test_damage_rules():
    pre = [{"part": "hood", "grade": "minor"}]
    L = pricing.damage_lines
    assert L(pre, [{"part": "hood", "grade": "minor", "photo_id": 1}])[0].fee == 0           # 대여 전 흠집
    assert L(pre, [{"part": "roof", "grade": "severe", "photo_id": 1}])[0].fee == 500_000      # 새 흠집
    assert L(pre, [{"part": "hood", "grade": "major", "photo_id": 1}])[0].fee == 120_000      # 악화분만
    two = L(pre, [{"part": "hood", "grade": "minor", "photo_id": 1}, {"part": "hood", "grade": "minor", "photo_id": 2}])
    assert sorted(x.fee for x in two) == [0, 30_000]                                         # 상쇄는 1건뿐
    with pytest.raises(ValueError):
        L(pre, [{"part": "roof", "grade": "minor", "photo_id": None}])                       # 사진 없음


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, user):
    c = TestClient(app)
    assert c.post("/api/login", json={"username": user, "password": "demo1234"}).status_code == 200
    return c


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_customer_isolation(client):
    kim, lee = login(client, "kim"), login(client, "lee")
    kim_ids = {r["id"] for r in kim.get("/api/rentals").json()}
    lee_ids = {r["id"] for r in lee.get("/api/rentals").json()}
    assert kim_ids and lee_ids and not kim_ids & lee_ids
    assert kim.get(f"/api/rentals/{next(iter(lee_ids))}").status_code == 404
    # 남의 사진, 직원 전용 API
    lee_photo = lee.get(f"/api/rentals/{next(iter(lee_ids))}").json()["checkout_damages"][0]["photo_id"]
    assert kim.get(f"/api/photos/{lee_photo}").status_code == 404
    assert lee.get(f"/api/photos/{lee_photo}").status_code == 200
    assert kim.post("/api/photos", files={"file": ("a.png", PNG, "image/png")}).status_code == 403
    assert kim.post(f"/api/rentals/{next(iter(kim_ids))}/return", json={}).status_code == 403
    assert client.get("/api/rentals").status_code == 401


def test_return_flow(client):
    staff = login(client, "staff1")
    r = next(x for x in staff.get("/api/rentals").json() if x["customer"] == "이고객" and x["status"] == "active")
    rid = r["id"]
    pre = {d["part"] for d in r["checkout_damages"]}
    assert "door_fl" in pre
    now = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M")
    base = {"returned_at": now, "fuel": 4, "odometer": 40300}

    # 사진 없는 흠집은 거절
    assert staff.post(f"/api/rentals/{rid}/return/preview", json={**base, "damages": [{"part": "roof", "grade": "minor"}]}).status_code == 422
    # 가짜 이미지 거절
    assert staff.post("/api/photos", files={"file": ("a.png", b"<svg onload=1>", "image/png")}).status_code == 415
    p1 = staff.post("/api/photos", files={"file": ("a.png", PNG, "image/png")}).json()["photo_id"]
    p2 = staff.post("/api/photos", files={"file": ("b.png", PNG, "image/png")}).json()["photo_id"]
    dm = [{"part": "door_fl", "grade": "major", "photo_id": p1}, {"part": "roof", "grade": "minor", "photo_id": p2}]
    # 주행거리 감소 거절
    assert staff.post(f"/api/rentals/{rid}/return/preview", json={**base, "odometer": 1, "damages": dm}).status_code == 422

    prev = staff.post(f"/api/rentals/{rid}/return/preview", json={**base, "damages": dm}).json()
    assert prev["fuel_fee"] == 2 * 15_000 and prev["damage_fee"] == 30_000 and prev["late_fee"] == 0
    assert prev["total"] == 60_000

    out = staff.post(f"/api/rentals/{rid}/return", json={**base, "damages": dm}).json()
    assert out["status"] == "returned" and out["return"]["total"] == 60_000
    # 재반납 거절, 사진 재사용 거절
    assert staff.post(f"/api/rentals/{rid}/return", json={**base, "damages": dm}).status_code == 409
    # 고객은 자기 청구 내역을 본다
    lee = login(client, "lee")
    mine = lee.get(f"/api/rentals/{rid}").json()
    assert mine["return"]["total"] == 60_000
    assert [d["fee"] for d in mine["return"]["damages"] if d["pre_existing"]] == [0]
