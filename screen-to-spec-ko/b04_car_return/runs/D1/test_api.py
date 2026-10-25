import json

import pytest
from fastapi.testclient import TestClient

import main
import seed

PNG = seed.make_png((1, 2, 3))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for mod in (main, seed):
        monkeypatch.setattr(mod, "UPLOAD_DIR", tmp_path / "up")
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "t.db")
    with TestClient(main.app) as c:
        yield c


def login(client, u, p):
    r = client.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200
    return client


def ret(client, rid, damages=(), files=(), **kw):
    data = {"returned_at": "2099-01-01T00:00", "fuel": "8", "odometer": "99999",
            "damages": json.dumps(list(damages)), **kw}
    return client.post(f"/api/rentals/{rid}/return", data=data,
                       files=[("photos", (f"{i}.png", f, "image/png")) for i, f in enumerate(files)])


def test_requires_login(client):
    assert client.get("/api/rentals").status_code == 401


def test_customer_sees_only_own(client):
    login(client, "kim", "kim1234")
    rows = client.get("/api/rentals").json()
    assert rows and {r["customer_name"] for r in rows} == {"김민수"}
    other = next(r for r in login(client, "staff", "staff1234") and client.get("/api/rentals").json()
                 if r["customer_name"] == "이서연")
    login(client, "kim", "kim1234")
    assert client.get(f"/api/rentals/{other['id']}").status_code == 404
    det = client.get("/api/rentals/1").json()
    assert client.get(f"/api/photos/{det['damages'][0]['id']}").status_code == 200


def test_customer_cannot_return_or_see_other_photo(client):
    login(client, "staff", "staff1234")
    lee = next(r for r in client.get("/api/rentals").json() if r["customer_name"] == "이서연")
    pid = client.get(f"/api/rentals/{lee['id']}").json()["damages"][0]["id"]
    login(client, "kim", "kim1234")
    assert ret(client, lee["id"]).status_code == 403
    assert client.get(f"/api/photos/{pid}").status_code == 404 or client.get(f"/api/photos/{pid}").status_code == 404


def test_damage_without_photo_rejected(client):
    login(client, "staff", "staff1234")
    r = ret(client, 3, [{"part": "roof", "grade": "minor", "photo": None}])
    assert r.status_code == 400 and "사진" in r.json()["detail"]
    assert client.get("/api/rentals/3").json()["status"] == "active"


def test_non_image_rejected(client):
    login(client, "staff", "staff1234")
    r = ret(client, 3, [{"part": "roof", "grade": "minor", "photo": 0}], [b"not an image"])
    assert r.status_code == 400


def test_return_flow_and_double_return(client):
    login(client, "staff", "staff1234")
    # 1번: 대여 때 앞 범퍼 경미 + 좌측 앞문 중간 / 연료 8
    dm = [{"part": "front_bumper", "grade": "minor", "photo": 0},      # 기존 → 0원
          {"part": "roof", "grade": "major", "photo": 1}]             # 신규 → 150,000
    dry = ret(client, 1, dm, [PNG, PNG], fuel="5", dry_run="true").json()
    assert dry["saved"] is False
    assert client.get("/api/rentals/1").json()["status"] == "active"
    res = ret(client, 1, dm, [PNG, PNG], fuel="5").json()
    assert res["saved"] and res["fuel_fee"] == 45_000 and res["damage_fee"] == 150_000
    assert res["late_fee"] > 0 and res["total"] == res["late_fee"] + 45_000 + 150_000
    assert ret(client, 1).status_code == 409
    login(client, "kim", "kim1234")
    mine = client.get("/api/rentals/1").json()
    assert mine["total"] == res["total"]
    assert sorted(d["charge"] for d in mine["damages"] if d["phase"] == "return") == [0, 150_000]


def test_validation(client):
    login(client, "staff", "staff1234")
    assert ret(client, 3, fuel="9").status_code == 400
    assert ret(client, 3, odometer="1").status_code == 400
    assert ret(client, 3, returned_at="2000-01-01T00:00").status_code == 400
    assert ret(client, 3, returned_at="garbage").status_code == 400
