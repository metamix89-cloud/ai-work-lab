import os
import sqlite3
import threading
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

TODAY = "2026-10-30"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MR_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("MR_FAKE_NOW", f"{TODAY} 10:15:30")
    import importlib
    import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        c.db = main.DB_PATH
        yield c


def post(c, **kw):
    body = dict(user_id=1, room_id=3, rsv_date=TODAY, start_time="11:00", end_time="11:30", title="회의")
    body.update(kw)
    return c.post("/api/reservations", json=body)


def test_seed_and_tables(client):
    assert len(client.get("/api/users").json()) == 5
    assert len(client.get("/api/rooms").json()) == 3
    assert 3 <= len(client.get("/api/reservations").json()) <= 5
    names = [r[0] for r in sqlite3.connect(client.db).execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    assert names and all(n.startswith("mr_") or n.startswith("sqlite_") for n in names)


def test_title_rules(client):
    assert post(client, title="   ").json()["detail"] == "제목을 입력해 주세요."
    assert post(client, title="가" * 31).status_code == 422
    assert post(client, title="가" * 30).status_code == 201


def test_time_boundaries(client):
    assert post(client, start_time="17:30", end_time="18:00").status_code == 201
    assert post(client, start_time="18:00", end_time="18:30").status_code == 422
    assert post(client, start_time="17:30", end_time="18:30").status_code == 422
    assert post(client, start_time="11:15", end_time="11:45").status_code == 422
    assert post(client, start_time="12:00", end_time="11:30").json()["detail"].startswith("종료")
    assert post(client, start_time="12:00", end_time="12:00").status_code == 422
    assert post(client, room_id=2, start_time="12:00", end_time="14:00").status_code == 201
    r = post(client, room_id=2, start_time="12:00", end_time="14:30")
    assert r.status_code == 422 and "2시간" in r.json()["detail"]
    assert post(client, start_time="9:00").json()["detail"] == "입력값을 확인해 주세요."


def test_overlap(client):
    assert post(client, start_time="11:00", end_time="12:00").status_code == 201
    assert post(client, start_time="11:30", end_time="12:30").status_code == 409
    assert post(client, start_time="12:00", end_time="12:30").status_code == 201  # 뒤에 맞닿음
    assert post(client, start_time="10:30", end_time="11:00").status_code == 201  # 앞에 맞닿음
    assert post(client, room_id=1, start_time="11:00", end_time="12:00", user_id=4).status_code in (201, 409)
    assert post(client, room_id=2, start_time="16:00", end_time="16:30").status_code == 201


def test_concurrent(client):
    results = []

    def go():
        results.append(post(client, start_time="15:30", end_time="16:00").status_code)

    # 15:30 은 seed 의 회의실 C 와 겹치지 않음
    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [201] + [409] * 5


def test_past_and_date(client):
    assert post(client, start_time="10:00", end_time="10:30").json()["detail"].startswith("이미 지난")
    assert post(client, start_time="10:30", end_time="11:00").status_code == 201
    assert post(client, rsv_date="2026-10-31", start_time="12:00", end_time="12:30").json()["detail"] == "오늘 날짜만 예약할 수 있습니다."


def test_exact_now_allowed(client, monkeypatch):
    monkeypatch.setenv("MR_FAKE_NOW", f"{TODAY} 13:00:40")
    assert post(client, start_time="13:00", end_time="13:30", room_id=1).status_code == 201


def test_user_room(client):
    assert post(client, user_id=99).status_code == 403
    assert post(client, room_id=99).status_code == 404
    assert post(client, user_id="x").status_code == 422
    assert post(client, title=None).status_code == 422


def test_cancel_flow(client):
    rid = post(client).json()["id"]
    r = client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 2})
    assert r.status_code == 403 and r.json()["detail"] == "본인의 예약만 취소할 수 있습니다."
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 1}).json()["status"] == "cancelled"
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 1}).status_code == 409
    assert post(client).status_code == 201  # 취소된 시간 재예약
    assert client.post("/api/reservations/9999/cancel", json={"user_id": 1}).status_code == 404
    row = sqlite3.connect(client.db).execute(
        "SELECT status, cancelled_at FROM mr_reservations WHERE id=?", (rid,)).fetchone()
    assert row[0] == "cancelled" and row[1]


def test_cancel_past(client):
    # seed 예약 1 (회의실 B 09:00~10:00, 사용자 1) 은 10:15 기준 끝남
    r = client.post("/api/reservations/1/cancel", json={"user_id": 1})
    assert r.status_code == 409 and r.json()["detail"] == "이미 끝난 예약은 취소할 수 없습니다."
    # 진행 중 예약(10:30 시작 후 시각) 취소 가능
    rid = client.post("/api/reservations", json=dict(
        user_id=1, room_id=3, rsv_date=TODAY, start_time="10:30", end_time="11:30", title="x")).json()["id"]
    os.environ["MR_FAKE_NOW"] = f"{TODAY} 11:00:00"
    assert client.post(f"/api/reservations/{rid}/cancel", json={"user_id": 1}).status_code == 200


def test_empty_list(client):
    c = sqlite3.connect(client.db)
    c.execute("UPDATE mr_reservations SET status='cancelled'")
    c.commit()
    r = client.get("/api/reservations")
    assert r.status_code == 200 and r.json() == []
