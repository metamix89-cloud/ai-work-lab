import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main  # noqa: E402

FIXED_NOW = datetime(2026, 10, 30, 12, 0, 0)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(main, "now_kst", lambda: FIXED_NOW)
    main.init_db()
    return TestClient(main.app)


def reserve(c, room=1, user=1, slot="14:00"):
    return c.post("/api/reservations", json={"room_id": room, "user_id": user, "slot_start": slot})


def test_t01_t03_schedule_and_seed(client):
    d = client.get("/api/schedule").json()
    assert len(d["rooms"]) == 3 and len(d["slots"]) == 18
    assert d["slots"][0] == "09:00" and d["slots"][-1] == "17:30"
    assert len(d["users"]) >= 8


def test_t05_reserve_shows_name(client):
    assert reserve(client).status_code == 201
    r = client.get("/api/schedule").json()["reservations"]
    assert r[0]["user_name"] == "김가온" and r[0]["slot_start"] == "14:00"


def test_t07_past_slot_rejected(client):
    assert reserve(client, slot="11:30").status_code == 400
    assert reserve(client, slot="12:00").status_code == 201  # 지금 시작하는 칸은 가능


def test_invalid_slot_rejected(client):
    assert reserve(client, slot="08:30").status_code == 400
    assert reserve(client, slot="18:00").status_code == 400
    assert reserve(client, slot="14:15").status_code == 400


def test_t08_duplicate_rejected(client):
    assert reserve(client).status_code == 201
    assert reserve(client, user=2).status_code == 409
    assert reserve(client, room=2, user=2).status_code == 201  # 다른 방은 가능


def test_t09_concurrent_only_one_wins(client):
    codes = []
    def go(uid):
        codes.append(reserve(client, user=uid, slot="15:00").status_code)
    ts = [threading.Thread(target=go, args=(u,)) for u in range(1, 7)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [201] + [409] * 5


def test_t10_t13_cancel_and_rebook(client):
    rid = reserve(client).json()["id"]
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 1}).status_code == 200
    assert client.get("/api/schedule").json()["reservations"] == []
    assert reserve(client, user=2).status_code == 201
    rows = sqlite3.connect(main.DB_PATH).execute(
        "SELECT status, cancelled_at FROM mr_reservations ORDER BY id").fetchall()
    assert rows[0][0] == "cancelled" and rows[0][1] and rows[1][0] == "active"


def test_t11_other_user_cannot_cancel(client):
    rid = reserve(client).json()["id"]
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 2}).status_code == 403


def test_t12_started_reservation_cannot_cancel(client, monkeypatch):
    rid = reserve(client, slot="13:00").json()["id"]
    monkeypatch.setattr(main, "now_kst", lambda: datetime(2026, 10, 30, 13, 0, 0))
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 1}).status_code == 400


def test_t14_table_names(client):
    names = [r[0] for r in sqlite3.connect(main.DB_PATH).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    assert names and all(n.startswith("mr_") for n in names)
