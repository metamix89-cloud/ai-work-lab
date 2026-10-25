import os
import tempfile

os.environ["RENTAL_DATA_DIR"] = tempfile.mkdtemp()

import json  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import photos  # noqa: E402
from app.main import app  # noqa: E402

PNG = photos.placeholder_png((1, 2, 3), 4)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, u, p):
    c = TestClient(app)
    assert c.post("/api/login", json={"username": u, "password": p}).status_code == 200
    return c


def active(c, customer=None):
    return [r for r in c.get("/api/rentals").json() if r["status"] == "active" and
            (customer is None or r["customer_name"] == customer)]


def submit(c, rid, damages=(), fuel=8, odo=10**7, returned_at=None, files=None):
    from app.service import now_kst
    data = {"returned_at": returned_at or now_kst().strftime("%Y-%m-%dT%H:%M"), "end_fuel": str(fuel),
            "end_odometer": str(odo), "damages": json.dumps(list(damages))}
    files = files if files is not None else {f"photo_{i}": ("a.png", PNG, "image/png") for i in range(len(damages))}
    return c.post(f"/api/rentals/{rid}/return", data=data, files=files or None)


def test_login_required_and_bad_password(client):
    assert client.get("/api/rentals").status_code == 401
    assert client.post("/api/login", json={"username": "kim", "password": "x"}).status_code == 401


def test_customer_sees_only_own(client):
    kim = login(client, "kim", "kim1234")
    rows = kim.get("/api/rentals").json()
    assert rows and {r["customer_name"] for r in rows} == {"김민준"}
    lee_id = active(login(client, "staff", "staff1234"), "이서연")[0]["id"]
    assert kim.get(f"/api/rentals/{lee_id}").status_code == 404
    dmg = login(client, "staff", "staff1234").get(f"/api/rentals/{lee_id}").json()["damages"][0]["id"]
    assert kim.get(f"/api/photos/{dmg}").status_code == 404
    assert kim.post(f"/api/rentals/{lee_id}/return", data={}).status_code == 403


def test_no_photo_rejected_and_nothing_saved(client):
    staff = login(client, "staff", "staff1234")
    rid = active(staff, "김민준")[0]["id"]
    r = submit(staff, rid, [{"part": "hood", "grade": "minor"}], files={})
    assert r.status_code == 422 and "사진" in r.json()["detail"]
    assert staff.get(f"/api/rentals/{rid}").json()["status"] == "active"


def test_non_image_rejected(client):
    staff = login(client, "staff", "staff1234")
    rid = active(staff, "김민준")[0]["id"]
    r = submit(staff, rid, [{"part": "hood", "grade": "minor"}], files={"photo_0": ("a.png", b"not an image", "image/png")})
    assert r.status_code == 422


def test_pre_existing_free_new_charged_and_total(client):
    staff = login(client, "staff", "staff1234")
    rid = [r for r in active(staff, "이서연") if r["start_fuel"] == 7][0]["id"]  # 상한 케이스 (10시간 지연), 연료 7
    d = staff.get(f"/api/rentals/{rid}").json()
    bumper = [x for x in d["damages"] if x["part"] == "front_bumper"][0]
    r = submit(staff, rid, fuel=5, damages=[
        {"part": "front_bumper", "grade": "major", "pre_existing_id": bumper["id"]},   # 대여 전 → 0
        {"part": "left_fender", "grade": "severe"},                                    # 새 흠집 → 500,000
    ])
    assert r.status_code == 200, r.text
    # 지연 상한 80,000 + 연료 2칸 30,000 + 심각 500,000
    assert r.json()["total_charge"] == 80_000 + 30_000 + 500_000
    after = login(client, "lee", "lee1234").get(f"/api/rentals/{rid}").json()
    by = {c["kind"] + str(c["damage_id"] or ""): c["amount"] for c in after["charges"]}
    assert sorted(c["amount"] for c in after["charges"] if c["kind"] == "damage") == [0, 500_000]
    assert any(x["pre_existing"] and x["phase"] == "return" for x in after["damages"])  # 기록은 남음
    # 이중 반납 불가
    assert submit(staff, rid).status_code == 409


def test_cannot_link_foreign_or_worsened_or_mismatched(client):
    staff = login(client, "staff", "staff1234")
    kim_rid = [r for r in active(staff, "김민준") if r["start_fuel"] == 8][0]["id"]
    lee_rid = [r for r in staff.get("/api/rentals").json() if r["customer_name"] == "이서연" and r["start_fuel"] == 7][0]["id"]
    foreign = staff.get(f"/api/rentals/{lee_rid}").json()["damages"][0]
    assert submit(staff, kim_rid, [{"part": foreign["part"], "grade": foreign["grade"],
                                    "pre_existing_id": foreign["id"]}]).status_code == 422
    own = staff.get(f"/api/rentals/{kim_rid}").json()["damages"][0]  # 좌 앞문 minor
    assert submit(staff, kim_rid, [{"part": own["part"], "grade": "major", "pre_existing_id": own["id"]}]).status_code == 422
    assert submit(staff, kim_rid, [{"part": "hood", "grade": "minor", "pre_existing_id": own["id"]}]).status_code == 422
    assert staff.get(f"/api/rentals/{kim_rid}").json()["status"] == "active"


def test_validation_fuel_odometer_future(client):
    staff = login(client, "staff", "staff1234")
    rid = active(staff, "박지호")[0]["id"]
    assert submit(staff, rid, fuel=9).status_code == 422
    assert submit(staff, rid, odo=1).status_code == 422   # 시작 주행거리보다 작음
    assert submit(staff, rid, returned_at="2099-01-01T00:00").status_code == 422
    assert staff.get(f"/api/rentals/{rid}").json()["status"] == "active"


def test_late_and_early_through_api(client):
    staff = login(client, "staff", "staff1234")
    early = [r for r in active(staff, "이서연")][0]  # 반납 예정이 미래인 건
    r = submit(staff, early["id"], fuel=8)
    assert r.status_code == 200 and r.json()["total_charge"] == 0
