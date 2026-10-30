import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

os.environ["RSV_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")

import pytest
from fastapi.testclient import TestClient

import main

NOW = datetime(2026, 10, 30, 10, 10, 0)
TODAY = "2026-10-30"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(main, "now_kst", lambda: NOW)
    if os.path.exists(main.DB_PATH):
        os.remove(main.DB_PATH)
    main.init_db()
    c = main.connect()
    c.execute("DELETE FROM rsv_booking")
    c.close()
    yield


client = TestClient(main.app, raise_server_exceptions=False)


def book(user=1, room=1, start=4, end=5, title="회의", date=TODAY):
    h = {} if user is None else {"X-User-Id": str(user)}
    return client.post("/api/bookings", headers=h, json=dict(
        room_id=room, book_date=date, start_slot=start, end_slot=end, title=title))


def cancel(bid, user=1):
    h = {} if user is None else {"X-User-Id": str(user)}
    return client.post(f"/api/bookings/{bid}/cancel", headers=h)


def test_empty_timetable():
    j = client.get("/api/timetable").json()
    assert j["bookings"] == [] and len(j["rooms"]) == 3


def test_create_and_user_checks():
    assert book().status_code == 201
    assert book(user=None).status_code == 400
    assert book(user=99).json()["message"] == main.MSG_USER
    assert book(room=9).json()["message"] == main.MSG_ROOM


def test_user_from_header_not_body():
    r = client.post("/api/bookings", headers={"X-User-Id": "2"}, json=dict(
        room_id=1, book_date=TODAY, start_slot=4, end_slot=5, title="x", user_id=3))
    assert r.json()["user_id"] == 2


def test_adjacent_and_overlap():
    assert book(start=4, end=5).status_code == 201     # 11:00~11:30
    assert book(start=5, end=6).status_code == 201     # 바로 뒤
    assert book(start=3, end=4).status_code == 201     # 바로 앞
    r = book(start=4, end=6)
    assert r.status_code == 409 and r.json()["message"] == main.MSG_OVERLAP


def test_length_and_range():
    assert book(start=4, end=12).status_code == 201     # 8칸
    assert book(room=2, start=4, end=13).json()["message"] == main.MSG_LEN
    assert book(start=17, end=18).status_code == 201
    for s, e in [(17, 19), (18, 19), (5, 5), (6, 5), (-1, 2)]:
        assert book(start=s, end=e).status_code == 400
    assert book(start="4", end=5).status_code == 400
    assert book(start=4.0, end=5).status_code == 400


def test_title():
    assert book(title="   ").json()["message"] == main.MSG_TITLE
    assert book(title="가" * 31).status_code == 400
    assert book(title="가" * 30).status_code == 201


def test_past_boundary():
    # 현재 10:10 -> 10:00 칸(2)은 불가, 10:30 칸(3)은 가능
    assert book(start=2, end=3).json()["message"] == main.MSG_PAST
    assert book(start=3, end=4).status_code == 201
    assert book(start=0, end=1).status_code == 400
    assert book(date="2026-10-31").status_code == 400


def test_exact_start_is_past(monkeypatch):
    monkeypatch.setattr(main, "now_kst", lambda: datetime(2026, 10, 30, 10, 30, 0))
    assert book(start=3, end=4).status_code == 400
    assert book(start=4, end=5).status_code == 201


def test_cancel_rules():
    bid = book().json()["booking_id"]
    assert cancel(bid, user=2).status_code == 403
    assert cancel(bid, user=None).status_code == 400
    assert cancel(999).status_code == 404
    r = cancel(bid)
    assert r.status_code == 200 and r.json()["status"] == "CANCELED"
    assert cancel(bid).json()["message"] == main.MSG_CANCELED
    assert book().status_code == 201   # 취소 자리 재예약


def test_cancel_started():
    c = main.connect()
    c.execute("INSERT INTO rsv_booking (room_id,user_id,book_date,start_slot,end_slot,"
              "title,status,created_at) VALUES (1,1,?,2,6,'t','ACTIVE','x')", (TODAY,))
    c.close()
    bid = client.get("/api/timetable").json()["bookings"][0]["booking_id"]
    r = cancel(bid)
    assert r.status_code == 409 and r.json()["message"] == main.MSG_CANCEL_PAST


def test_concurrent():
    with ThreadPoolExecutor(8) as ex:
        codes = sorted(f.result().status_code for f in [ex.submit(book, 1 + i % 5) for i in range(8)])
    assert codes.count(201) == 1 and codes.count(409) == 7


def test_seed_and_tables():
    c = main.connect()
    names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert all(n.startswith("rsv_") for n in names if not n.startswith("sqlite_"))
    assert c.execute("SELECT COUNT(*) FROM rsv_user").fetchone()[0] == 5
    c.close()
