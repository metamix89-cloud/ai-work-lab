from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main

T0 = datetime(2026, 10, 30, 10, 0, 0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = {"t": T0}
    monkeypatch.setattr(main, "now", lambda: clock["t"])
    main.init_db(str(tmp_path / "t.db"), seed_data=False)
    main.sessions.clear()
    main.fails.clear()
    return TestClient(main.app), clock


def person(name="김민수", wt="deposit"):
    return {"name": name, "phone": "010-0000-4878", "account": "110-1234-5678-901", "work_type": wt}


def login(c, window=None, role="teller"):
    pin = main.TELLER_PINS[window] if role == "teller" else main.MANAGER_PIN
    r = c.post("/api/login", json={"role": role, "window": window, "pin": pin}).json()
    return {"X-Token": r["token"]}


def reserve_and_arrive(c, clock, offset_min, name="예약자"):
    """예약 시각이 도착 시각보다 offset_min 분 뒤(음수면 앞)인 상황을 만든다."""
    at = clock["t"] + timedelta(minutes=60)
    r = c.post("/api/reservations", json={**person(name), "reserved_at": at.isoformat()})
    assert r.status_code == 200, r.text
    clock["t"] = at - timedelta(minutes=offset_min)
    return c.post("/api/reservations/checkin", json={"code": r.json()["code"], "phone_last4": "5678"}).json()


@pytest.mark.parametrize("offset,prio", [(10, True), (-10, True), (11, False), (-11, False), (0, True)])
def test_priority_window(env, offset, prio):
    c, clock = env
    assert reserve_and_arrive(c, clock, offset)["priority"] is prio


def test_priority_called_before_earlier_walkin(env):
    c, clock = env
    c.post("/api/tickets", json=person("일반인"))              # A001
    clock["t"] += timedelta(minutes=1)
    assert reserve_and_arrive(c, clock, 5)["number"] == "A002"  # 우선
    h = login(c, 1)
    c.post("/api/teller/call-next", headers=h)
    assert c.get("/api/teller/state", headers=h).json()["current"]["number"] == "A002"


def test_window_only_calls_own_type_and_sees_only_own(env):
    c, clock = env
    c.post("/api/tickets", json=person("대출인", "loan"))        # B001
    c.post("/api/tickets", json=person("예금인", "deposit"))     # A001
    h4 = login(c, 4)
    assert c.post("/api/teller/call-next", headers=h4).status_code == 404   # 외환 대기 없음
    h3 = login(c, 3)
    assert c.post("/api/teller/call-next", headers=h3).status_code == 200
    cur = c.get("/api/teller/state", headers=h3).json()["current"]
    assert cur["number"] == "B001" and cur["account_last4"] == "8901"
    tid = cur["id"]
    # 다른 창구 직원은 상세/조작 불가
    assert c.post(f"/api/teller/{tid}/start", headers=h4).status_code == 404
    h1 = login(c, 1)
    assert c.post(f"/api/teller/{tid}/start", headers=h1).status_code == 404
    assert "예금인" not in str(c.get("/api/teller/state", headers=h3).json()["waiting"])


def test_timeout_hold_and_autocall_next(env):
    c, clock = env
    c.post("/api/tickets", json=person("첫째"))
    c.post("/api/tickets", json=person("둘째"))
    h = login(c, 1)
    c.post("/api/teller/call-next", headers=h)
    clock["t"] += timedelta(minutes=2, seconds=59)
    assert c.get("/api/teller/state", headers=h).json()["current"]["number"] == "A001"
    clock["t"] += timedelta(seconds=1)
    s = c.get("/api/teller/state", headers=h).json()
    assert s["current"]["number"] == "A002"
    assert [x["number"] for x in s["hold"]] == ["A001"]
    m = c.get("/api/manager/summary", headers=login(c, role="manager")).json()
    assert m["noshow_after_call"] == 1 and m["on_hold_now"] == 1


def test_start_stops_timeout(env):
    c, clock = env
    c.post("/api/tickets", json=person())
    h = login(c, 1)
    c.post("/api/teller/call-next", headers=h)
    tid = c.get("/api/teller/state", headers=h).json()["current"]["id"]
    assert c.post(f"/api/teller/{tid}/start", headers=h).status_code == 200
    clock["t"] += timedelta(minutes=30)
    assert c.get("/api/teller/state", headers=h).json()["current"]["status"] == "serving"


def test_display_leaks_nothing(env):
    c, _ = env
    c.post("/api/tickets", json=person("김민수"))
    c.post("/api/tickets", json=person("이영희"))
    login_h = login(c, 1)
    c.post("/api/teller/call-next", headers=login_h)
    body = c.get("/api/display").json()
    text = str(body)
    for secret in ["김민수", "이영희", "010-0000-7907", "5678", "901"]:
        assert secret not in text
    assert set(body["waiting"][0]) == {"number", "name"}
    assert body["windows"][0] == {"window": 1, "number": "A001", "name": "김*수"}


def test_manager_numbers_only_and_auth(env):
    c, _ = env
    c.post("/api/tickets", json=person("김민수"))
    assert c.get("/api/manager/summary").status_code == 401
    assert c.get("/api/manager/summary", headers=login(c, 1)).status_code == 401   # 창구 토큰은 불가
    assert c.get("/api/teller/state", headers=login(c, role="manager")).status_code == 401
    text = str(c.get("/api/manager/summary", headers=login(c, role="manager")).json())
    assert "김" not in text and "0101234" not in text


def test_reservation_noshow_and_account_stored_last4(env):
    c, clock = env
    at = clock["t"] + timedelta(minutes=5)
    c.post("/api/reservations", json={**person(), "reserved_at": at.isoformat()})
    row = main._conn.execute("SELECT account_last4 FROM reservations").fetchone()
    assert row["account_last4"] == "8901"
    mh = login(c, role="manager")
    assert c.get("/api/manager/summary", headers=mh).json()["noshow_reservation"] == 0
    clock["t"] += timedelta(minutes=16)
    assert c.get("/api/manager/summary", headers=mh).json()["noshow_reservation"] == 1


def test_bad_pin_and_validation(env):
    c, _ = env
    assert c.post("/api/login", json={"role": "teller", "window": 1, "pin": "0000"}).status_code == 401
    assert c.post("/api/tickets", json={**person(), "account": "123"}).status_code == 422
    assert c.post("/api/tickets", json={**person(), "work_type": "x"}).status_code == 422
