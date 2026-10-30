import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DUDUK_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import core  # noqa: E402

T0 = datetime(2026, 11, 2, 10, 0, 0)  # 월요일


@pytest.fixture
def db(monkeypatch):
    clock = {"t": T0}
    monkeypatch.setattr(core, "now", lambda: clock["t"])
    import sqlite3

    class Conn(sqlite3.Connection):
        pass

    c = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False, factory=Conn)
    c.row_factory = sqlite3.Row
    core.init_db(c)
    c.clock = clock
    return c


def reserve(db, service, at):
    return core.create_reservation(db, "홍길동", "010-0000-7907", "1234", service, at)


def test_mask_name():
    assert core.mask_name("김민수") == "김*수"
    assert core.mask_name("남궁민수") == "남**수"
    assert core.mask_name("김수") == "김*"


def test_reserved_within_10min_goes_first(db):
    walk, _ = core.walk_in(db, "일반", "010-0000-4634", "1111", "deposit")
    db.clock["t"] = T0 + timedelta(minutes=5)
    code = reserve(db, "deposit", T0 + timedelta(minutes=14))  # 도착 5분 -> 예약 9분 뒤: 범위 안
    _, prio, _ = core.check_in(db, code)
    assert prio == 1
    wid = core.call_next(db, 1)
    assert db.execute("SELECT ticket_no FROM visits WHERE id=?", (wid,)).fetchone()[0] != walk  # 예약 고객이 먼저


def test_priority_boundary_and_outside(db):
    r = T0
    db.clock["t"] = r + timedelta(minutes=10)
    _, p10, _ = core.check_in(db, reserve(db, "deposit", r))
    db.clock["t"] = r + timedelta(minutes=10, seconds=1)
    _, p11, _ = core.check_in(db, reserve(db, "deposit", r))
    db.clock["t"] = r - timedelta(minutes=11)
    _, early, _ = core.check_in(db, reserve(db, "loan", r))
    assert (p10, p11, early) == (1, 0, 0)


def test_late_reservation_uses_general_order(db):
    first, _ = core.walk_in(db, "일반", "010-0000-4634", "1111", "deposit")
    db.clock["t"] = T0 + timedelta(minutes=30)
    code = reserve(db, "deposit", T0)
    core.check_in(db, code)  # 30분 늦음 -> 일반
    wid = core.call_next(db, 1)
    assert db.execute("SELECT ticket_no FROM visits WHERE id=?", (wid,)).fetchone()[0] == first


def test_window_only_calls_own_service(db):
    core.walk_in(db, "예금", "010-0000-4634", "1111", "deposit")
    assert core.call_next(db, 3) is None  # 대출 창구엔 대출 고객이 없음
    assert core.call_next(db, 4) is None
    assert isinstance(core.call_next(db, 2), int)


def test_no_show_after_3min_holds_and_calls_next(db):
    a, _ = core.walk_in(db, "가", "010-0000-4634", "1111", "deposit")
    b, _ = core.walk_in(db, "나", "010-0000-4634", "2222", "deposit")
    core.call_next(db, 1)
    db.clock["t"] += timedelta(minutes=2, seconds=59)
    core.expire_calls(db)
    assert db.execute("SELECT status FROM visits WHERE ticket_no=?", (a,)).fetchone()[0] == "called"
    db.clock["t"] += timedelta(seconds=2)
    core.expire_calls(db)
    assert db.execute("SELECT status FROM visits WHERE ticket_no=?", (a,)).fetchone()[0] == "hold"
    row = db.execute("SELECT status, window FROM visits WHERE ticket_no=?", (b,)).fetchone()
    assert (row[0], row[1]) == ("called", 1)


def test_manager_summary_has_no_personal_data(db):
    core.walk_in(db, "김민수", "010-0000-7663", "4321", "deposit")
    s = str(core.manager_summary(db))
    for bad in ("김민수", "010-0000-7663", "4321"):
        assert bad not in s


# ---- API ----
@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(c, **kw):
    return {"Authorization": "Bearer " + c.post("/api/login", json=kw).json()["token"]}


def test_display_exposes_only_ticket_masked_name_window(client):
    d = client.get("/api/display").json()
    assert d["calling"] and d["waiting"]
    for x in d["calling"]:
        assert set(x) == {"ticket", "name", "window", "state"} and "*" in x["name"]
    for x in d["waiting"]:
        assert set(x) == {"ticket", "name"} and "*" in x["name"]


def test_auth_required_and_wrong_pin(client):
    assert client.get("/api/teller/state").status_code == 401
    assert client.get("/api/manager/summary").status_code == 401
    assert client.post("/api/login", json={"role": "teller", "window": 1, "pin": "0000"}).status_code == 401
    mh = login(client, role="manager", pin="9999")
    assert client.get("/api/teller/state", headers=mh).status_code == 403  # 지점장은 창구 상세 불가
    th = login(client, role="teller", window=1, pin="1111")
    assert client.get("/api/manager/summary", headers=th).status_code == 403


def test_teller_sees_only_own_window_and_last4(client):
    h1 = login(client, role="teller", window=1, pin="1111")
    h3 = login(client, role="teller", window=3, pin="3333")
    cur1 = client.get("/api/teller/state", headers=h1).json()["current"]
    assert cur1 and cur1["account"].startswith("****") and len(cur1["account"]) == 8
    cur3 = client.get("/api/teller/state", headers=h3).json()["current"]
    assert cur3 is None or cur3["name"] != cur1["name"]
    for x in client.get("/api/teller/state", headers=h3).json()["waiting"]:
        assert set(x) == {"ticket", "name", "priority"}  # 대기 목록엔 상세 없음


def test_input_validation(client):
    bad = {"name": "<script>", "phone": "010", "account": "abc", "service": "x"}
    assert client.post("/api/tickets", json=bad).status_code == 422
    ok = {"name": "테스트", "phone": "010-0000-4398", "account": "110-123-456789", "service": "fx"}
    assert client.post("/api/tickets", json=ok).status_code == 200
