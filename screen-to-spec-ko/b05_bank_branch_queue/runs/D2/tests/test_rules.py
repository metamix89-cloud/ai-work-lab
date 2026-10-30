import os
import sqlite3
import tempfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["DUDUK_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from app import main  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def login(client, role, counter=None, pin=None):
    pin = pin or ("9999" if role == "manager" else str(counter) * 4)
    r = client.post("/api/login", json={"role": role, "counter": counter, "pin": pin})
    assert r.status_code == 200, r.text
    return {"X-Token": r.json()["token"]}


def test_display_exposes_only_number_masked_name_counter(client):
    d = client.get("/api/display").json()
    assert d["waiting"] and d["calling"]
    for w in d["waiting"]:
        assert set(w) == {"number", "name", "counters"}
        assert "*" in w["name"]
    blob = client.get("/api/display").text
    for secret in ("0101111", "110-", "김철수", "서지후", "임수아"):
        assert secret not in blob


def test_priority_and_late_reserved(client):
    h4 = login(client, "counter", 4)
    # 임수아(예약 ±10분, 외환)가 먼저 도착한 배도현보다 앞
    st = client.get("/api/counter/state", headers=h4).json()
    assert [w["name"] for w in st["waiting"]] == ["임*아", "배*현"]
    assert st["waiting"][0]["priority"]
    # 예약 +25분 늦게 온 오하늘(예금)은 일반 순서: 강동원/윤서연 뒤
    h1 = login(client, "counter", 1)
    names = [w["name"] for w in client.get("/api/counter/state", headers=h1).json()["waiting"]]
    assert names == ["서*후", "강*원", "윤*연", "오*늘"]


def test_counter_only_own_service_and_detail_masking(client):
    h4 = login(client, "counter", 4)
    assert client.post("/api/counter/call-next", headers=h4).status_code == 200
    cur = client.get("/api/counter/state", headers=h4).json()["current"]
    assert cur["name"] == "임수아" and cur["service"] == "외환"
    assert cur["account"] == "****9013" and "440" not in str(cur)
    # 다른 창구는 그 고객을 못 봄
    h3 = login(client, "counter", 3)
    assert cur["name"] not in client.get("/api/counter/state", headers=h3).text
    # 응대 끝내기 전 재호출 불가
    assert client.post("/api/counter/call-next", headers=h4).status_code == 409


def test_timeout_holds_and_calls_next(client):
    h4 = login(client, "counter", 4)
    with sqlite3.connect(main.DB_PATH) as c:
        old = main.iso(main.now() - timedelta(minutes=4))
        c.execute("UPDATE tickets SET called_at=? WHERE status='called' AND counter=4", (old,))
    st = client.get("/api/counter/state", headers=h4).json()
    assert st["current"]["name"] == "배도현"
    assert [h["name"] for h in st["hold"]] == ["임*아"]


def test_manager_numbers_only_and_roles(client):
    hm = login(client, "manager")
    r = client.get("/api/manager/stats", headers=hm)
    assert r.status_code == 200
    for secret in ("김철수", "01011", "110-"):
        assert secret not in r.text
    assert r.json()["total"]["noshow"] >= 2
    assert client.get("/api/manager/stats").status_code == 401
    assert client.get("/api/counter/state", headers=hm).status_code == 403
    h1 = login(client, "counter", 1)
    assert client.get("/api/manager/stats", headers=h1).status_code == 403
    assert client.post("/api/login", json={"role": "manager", "pin": "0000"}).status_code == 401


def test_reservation_checkin_priority(client):
    when = main.iso(main.now() + timedelta(minutes=1))
    with main.tx() as c:  # 영업시간 검증을 우회해 시계와 무관하게 체크인 규칙만 확인
        main.add_ticket(c, name="테스트", phone="010-0000-4084", account="123-456-789012",
                        service="대출", kind="reserved", reserved_at=when)
    bad = client.post("/api/checkin", json={"phone": "010-0000-4084", "account_last4": "0000"})
    assert bad.status_code == 404
    r = client.post("/api/checkin", json={"phone": "010-0000-4301", "account_last4": "9012"})
    assert r.status_code == 200 and r.json()["priority"] is True and r.json()["name"] == "테*트"


def test_reservation_rejects_outside_hours(client):
    d = (main.now() + timedelta(days=1)).replace(hour=20, minute=0)
    body = {"name": "테스트", "phone": "010-0000-2045", "account": "123-456-789012", "service": "예금",
            "reserved_at": d.isoformat()}
    assert client.post("/api/reservations", json=body).status_code == 422
    body["reserved_at"] = d.replace(hour=10).isoformat()
    assert client.post("/api/reservations", json=body).status_code == 200


def test_validation(client):
    bad = {"name": "A", "phone": "123", "account": "abc", "service": "보험"}
    assert client.post("/api/walkin", json=bad).status_code == 422
