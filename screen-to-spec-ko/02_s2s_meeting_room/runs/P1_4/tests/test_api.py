import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import main

TODAY = "2026-10-30"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(main, "now", lambda: datetime(2026, 10, 30, 10, 15))
    with TestClient(main.app) as c:
        yield c


def book(c, room=3, user=1, start="16:00", end="16:30", title="테스트"):
    return c.post("/api/reservations", json=dict(
        room_id=room, user_id=user, rsv_date=TODAY, start_time=start, end_time=end, title=title))


def test_seed_and_table_names(client):
    conn = sqlite3.connect(main.DB_PATH)
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert all(n.startswith("mr_") for n in names if not n.startswith("sqlite_"))  # T-15
    assert len(client.get("/api/users").json()) == 5
    assert len(client.get("/api/rooms").json()) == 3
    assert len(client.get("/api/reservations").json()["reservations"]) == 5  # T-02


def test_title_rules(client):  # T-07
    assert book(client, title="   ").status_code == 422
    assert book(client, title="가" * 31).status_code == 422
    assert book(client, title="가" * 30).status_code == 201


def test_time_limits(client):  # T-08
    assert book(client, start="12:00", end="14:30").status_code == 422  # 2시간 초과
    assert book(client, start="17:30", end="18:30").status_code == 422  # 18:00 초과
    assert book(client, start="12:00", end="12:15").status_code == 422  # 30분 단위 아님
    assert book(client, start="12:30", end="12:00").status_code == 422
    assert book(client, room=1, start="12:00", end="14:00").status_code == 201


def test_overlap_and_adjacent(client):  # T-09
    assert book(client, room=3, start="16:00", end="17:00").status_code == 201
    assert book(client, room=3, start="16:30", end="17:30").status_code == 409
    assert book(client, room=3, start="15:30", end="16:30").status_code == 409
    assert book(client, room=3, start="17:00", end="17:30").status_code == 201  # 맞닿음
    assert book(client, room=3, start="15:30", end="16:00").status_code == 201  # 맞닿음


def test_concurrent_same_slot(client):  # T-10
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda i: book(client, room=3, user=i % 5 + 1, start="12:00", end="13:00",
                                           title=f"동시{i}").status_code, range(8)))
    assert codes.count(201) == 1 and codes.count(409) == 7


def test_past_time(client):  # T-11
    assert book(client, start="10:00", end="10:30").status_code == 422
    assert book(client, start="10:30", end="11:00", room=3).status_code == 201


def test_cancel_flow(client):  # T-12, T-13, T-14
    rid = book(client, start="16:00", end="16:30").json()["id"]
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 2}).status_code == 403
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 1}).status_code == 200
    status = sqlite3.connect(main.DB_PATH).execute(
        "SELECT status, cancelled_at FROM mr_reservations WHERE id=?", (rid,)).fetchone()
    assert status[0] == "cancelled" and status[1]
    # 취소된 칸은 다시 예약 가능
    assert book(client, start="16:00", end="16:30").status_code == 201
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 1}).status_code == 409
    # 시드 중 09:00~10:00 예약은 현재(10:15) 기준 이미 끝남
    ended = [r for r in client.get("/api/reservations").json()["reservations"] if r["end_time"] == "10:00"][0]
    assert client.post(f"/api/reservations/{ended['id']}/cancel", json={"user_id": ended["user_id"]}).status_code == 422
