import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main  # noqa: E402

TODAY = "2026-10-30"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"))
    clock = {"t": datetime(2026, 10, 30, 10, 10)}
    monkeypatch.setattr(main, "now", lambda: clock["t"])
    with TestClient(main.app) as c:
        c.clock = clock
        yield c


def body(**kw):
    d = dict(user_id=1, room_id=3, rsv_date=TODAY, start_time="10:30", end_time="11:00", title="회의")
    d.update(kw)
    return d


def test_seed_once(client):
    d = client.get("/api/timetable").json()
    assert len(d["rooms"]) == 3 and len(d["users"]) == 5 and len(d["reservations"]) == 5
    main.init_db()  # 재실행해도 중복 적재 없음
    assert len(client.get("/api/timetable").json()["reservations"]) == 5


def test_create_and_touching(client):
    r = client.post("/api/reservations", json=body())
    assert r.status_code == 201
    assert client.post("/api/reservations", json=body(start_time="11:00", end_time="11:30")).status_code == 201
    r = client.post("/api/reservations", json=body(start_time="10:30", end_time="11:30"))
    assert (r.status_code, r.json()["detail"]) == (409, "이미 예약된 시간과 겹칩니다.")


def test_other_room_and_same_user_ok(client):
    assert client.post("/api/reservations", json=body(room_id=1, start_time="11:00", end_time="11:30")).status_code == 201


@pytest.mark.parametrize("kw,status,msg", [
    (dict(user_id=99), 422, "사용자를 선택해 주세요."),
    (dict(user_id=None), 422, "사용자를 선택해 주세요."),
    (dict(room_id=99), 422, "존재하지 않는 회의실입니다."),
    (dict(rsv_date="2026-10-31"), 422, "오늘 날짜만 예약할 수 있습니다."),
    (dict(rsv_date="garbage"), 422, "오늘 날짜만 예약할 수 있습니다."),
    (dict(start_time="10:45"), 422, "예약은 09:00~18:00 사이 30분 단위로만 가능합니다."),
    (dict(start_time="11:00", end_time="11:00"), 422, "예약은 09:00~18:00 사이 30분 단위로만 가능합니다."),
    (dict(start_time="17:30", end_time="18:30"), 422, "예약은 09:00~18:00 사이 30분 단위로만 가능합니다."),
    (dict(start_time="8:30"), 422, "예약은 09:00~18:00 사이 30분 단위로만 가능합니다."),
    (dict(start_time="10:30", end_time="13:00"), 422, "예약 시간은 30분 이상 2시간 이하여야 합니다."),
    (dict(title=""), 422, "제목을 입력해 주세요."),
    (dict(title="   "), 422, "제목을 입력해 주세요."),
    (dict(title="가" * 51), 422, "제목은 50자 이하로 입력해 주세요."),
    (dict(start_time="10:00", end_time="10:30"), 422, "이미 지난 시간은 예약할 수 없습니다."),
])
def test_rejections(client, kw, status, msg):
    r = client.post("/api/reservations", json=body(**kw))
    assert (r.status_code, r.json()["detail"]) == (status, msg)
    assert len(client.get("/api/timetable").json()["reservations"]) == 5


def test_boundaries_ok(client):
    assert client.post("/api/reservations", json=body(title="가" * 50)).status_code == 201
    assert client.post("/api/reservations", json=body(room_id=1, start_time="15:00", end_time="17:00")).status_code == 201
    assert client.post("/api/reservations", json=body(room_id=2, start_time="17:30", end_time="18:00")).status_code == 201


def test_start_equal_now_allowed(client):
    client.clock["t"] = datetime(2026, 10, 30, 10, 30, 45)  # 초는 내림
    assert client.post("/api/reservations", json=body(start_time="10:30", end_time="11:00")).status_code == 201


def test_cancel_rules(client):
    rid = client.post("/api/reservations", json=body()).json()["reservation_id"]
    r = client.delete(f"/api/reservations/{rid}", params={"user_id": 2})
    assert (r.status_code, r.json()["detail"]) == (403, "본인의 예약만 취소할 수 있습니다.")
    assert client.delete(f"/api/reservations/{rid}", params={"user_id": 1}).status_code == 200
    r = client.delete(f"/api/reservations/{rid}", params={"user_id": 1})
    assert r.status_code == 404


def test_cancel_ended_vs_in_progress(client):
    # 시드: 회의실 A 09:30~10:30(user1) — 10:10 현재 진행 중, 회의실 B 11:00~12:00(user3) 시작 전
    rsv = {(r["room_id"], r["start_time"]): r for r in client.get("/api/timetable").json()["reservations"]}
    inprog = rsv[(1, "09:30")]["reservation_id"]
    client.clock["t"] = datetime(2026, 10, 30, 10, 30)  # 종료 시각과 같음 → 종료됨
    r = client.delete(f"/api/reservations/{inprog}", params={"user_id": 1})
    assert (r.status_code, r.json()["detail"]) == (409, "이미 종료된 예약은 취소할 수 없습니다.")
    client.clock["t"] = datetime(2026, 10, 30, 10, 29)
    assert client.delete(f"/api/reservations/{inprog}", params={"user_id": 1}).status_code == 200


def test_concurrent_same_slot(client):
    codes = []
    barrier = threading.Barrier(8)

    def go(uid):
        barrier.wait()
        codes.append(client.post("/api/reservations", json=body(user_id=uid % 5 + 1, start_time="12:00", end_time="12:30")).status_code)

    ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [201] + [409] * 7
