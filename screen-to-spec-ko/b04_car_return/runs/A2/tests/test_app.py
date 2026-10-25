import os
import tempfile

os.environ["RENTAL_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import billing  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def login(u, p):
    r = client.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_billing_units():
    due = datetime(2026, 1, 1, 12)
    assert billing.late_line(due, due + timedelta(minutes=30), 60000) is None
    assert billing.late_line(due, due + timedelta(minutes=31), 60000)["amount"] == 6000      # 1h
    assert billing.late_line(due, due + timedelta(hours=20), 60000)["amount"] == 60000        # 일 요금 상한
    assert billing.fuel_line(8, 8, 47) is None and billing.fuel_line(5, 6, 47) is None
    assert billing.fuel_line(8, 4, 60)["amount"] == 81000
    pre = [{"part": "앞 범퍼", "grade": 2}]
    same = billing.damage_lines([{"part": "앞 범퍼", "grade": 2}], pre)[0]
    worse = billing.damage_lines([{"part": "앞 범퍼", "grade": 3}], pre)[0]
    new = billing.damage_lines([{"part": "본넷", "grade": 1}], pre)[0]
    assert (same["amount"], worse["amount"], new["amount"]) == (0, 280000, 30000)


def test_return_excludes_preexisting_and_blocks_double_submit():
    staff = login("staff1", "staff1234")
    rentals = client.get("/api/rentals", headers=staff).json()
    rid = next(r["id"] for r in rentals if r["customer_name"] == "홍길동" and r["status"] == "active" and r["model"] == "현대 아반떼")
    detail = client.get(f"/api/rentals/{rid}", headers=staff).json()
    body = {"returned_at": (datetime.now()).isoformat(timespec="minutes"), "odometer": 25_500, "fuel": 8,
            "damages": [{"part": "앞 범퍼", "grade": 1}, {"part": "운전석 앞문", "grade": 2}, {"part": "트렁크", "grade": 1}]}
    prev = client.post(f"/api/rentals/{rid}/preview", json=body, headers=staff).json()
    dmg = [l for l in prev["lines"] if l["type"] == "damage"]
    assert sorted(l["amount"] for l in dmg) == [0, 0, 30000]
    assert any(l["type"] == "late" for l in prev["lines"])  # 시드: 3시간 지연
    assert client.post(f"/api/rentals/{rid}/return", json=body, headers=staff).status_code == 200
    assert client.post(f"/api/rentals/{rid}/return", json=body, headers=staff).status_code == 409
    assert client.get(f"/api/rentals/{rid}", headers=staff).json()["total"] == prev["total"]
    assert detail["status"] == "active"


def test_validation():
    staff = login("staff1", "staff1234")
    rid = client.get("/api/rentals", headers=staff).json()[0]["id"]
    for patch in ({"odometer": 1}, {"fuel": 9}, {"damages": [{"part": "없는부위", "grade": 1}]},
                  {"damages": [{"part": "본넷", "grade": 9}]}):
        body = {"returned_at": datetime.now().isoformat(timespec="minutes"), "odometer": 99_999, "fuel": 8, **patch}
        assert client.post(f"/api/rentals/{rid}/preview", json=body, headers=staff).status_code in (422,)


def test_customer_isolation_and_roles():
    hong, kim = login("hong", "cust1234"), login("kim", "cust1234")
    mine = client.get("/api/rentals", headers=hong).json()
    assert mine and all(r["customer_name"] == "홍길동" for r in mine)
    kim_ids = [r["id"] for r in client.get("/api/rentals", headers=kim).json()]
    assert kim_ids and all(i not in [m["id"] for m in mine] for i in kim_ids)
    assert client.get(f"/api/rentals/{kim_ids[0]}", headers=hong).status_code == 404
    assert all(c["customer_name"] == "홍길동" for c in client.get("/api/charges", headers=hong).json())
    assert client.post(f"/api/rentals/{mine[0]['id']}/return", headers=hong,
                       json={"returned_at": "2026-01-01T00:00", "odometer": 1, "fuel": 1}).status_code == 403
    assert client.get("/api/rentals").status_code == 401


def test_photo_upload_and_access():
    staff, hong, kim = login("staff1", "staff1234"), login("hong", "cust1234"), login("kim", "cust1234")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    assert client.post("/api/uploads", files={"file": ("x.png", png, "image/png")}, headers=hong).status_code == 403
    assert client.post("/api/uploads", files={"file": ("x.png", b"not an image", "image/png")}, headers=staff).status_code == 400
    pid = client.post("/api/uploads", files={"file": ("x.png", png, "image/png")}, headers=staff).json()["id"]
    rid = next(r["id"] for r in client.get("/api/rentals", headers=staff).json() if r["customer_name"] == "홍길동" and r["status"] == "active")
    body = {"returned_at": datetime.now().isoformat(timespec="minutes"), "odometer": 99_999, "fuel": 0,
            "damages": [{"part": "지붕", "grade": 3, "photo_id": pid}]}
    assert client.post(f"/api/rentals/{rid}/return", json=body, headers=staff).status_code == 200
    assert client.get(f"/api/uploads/{pid}", headers=hong).status_code == 200
    assert client.get(f"/api/uploads/{pid}", headers=kim).status_code == 404
