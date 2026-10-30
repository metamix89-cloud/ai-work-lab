import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
import main

c = TestClient(main.app)
P = {"phone": "010-0000-1111", "account": "999-888-777666"}


def ticket(name, service="deposit", **kw):
    return c.post("/api/tickets", json={"name": name, "service": service, **P, **kw})


def test_pages_and_users():
    assert "대기" in c.get("/").text
    assert c.get("/board").status_code == 200
    assert len(c.get("/api/users").json()) == 5


def test_validation_and_board_masking():
    assert ticket("", "deposit").json()["detail"] == "이름을 확인하세요"
    assert ticket("a", "x").status_code == 400
    assert c.post("/api/tickets", json={"name": "a", "phone": "1", "account": "1", "service": "fx"}).status_code == 400
    r = ticket("남궁민수")
    assert r.status_code == 201 and "name" not in r.json() and "phone" not in r.json()
    b = c.get("/api/board").text
    assert "남**수" in b and "남궁민수" not in b and "010-" not in b and "deposit" not in b


def test_checkin_boundaries_and_rules():
    for at, pr in [("10:10", True), ("10:11", False), ("09:50", True), ("09:49", False)]:
        t = ticket("김민수", "loan", reserved_at="2026-10-30 10:00").json()
        assert t["status"] == "reserved"
        r = c.post(f"/api/tickets/{t['ticket_id']}/checkin", json={"at": f"2026-10-30 {at}"})
        assert r.json()["priority"] is pr
        assert c.post(f"/api/tickets/{t['ticket_id']}/checkin", json={"at": "2026-10-30 10:00"}).status_code == 409
    w = ticket("현장").json()
    assert c.post(f"/api/tickets/{w['ticket_id']}/checkin", json={}).status_code == 409


def test_hold_complete_permissions():
    for tid in ("K-05", "K-06"):  # make sure deposit line exists
        pass
    t1 = c.post("/api/counters/C3/next", json={"user": "t3", "at": "2026-10-30 12:00"}).json()
    assert t1["called"]["counter_id"] == "C3"
    assert c.post("/api/counters/C3/next", json={"user": "t3", "at": "2026-10-30 12:02"}).status_code == 409
    r = c.post("/api/counters/C3/next", json={"user": "t3", "at": "2026-10-30 12:03"}).json()
    assert r["held"] == t1["called"]["ticket_id"]
    cid = r["called"]["ticket_id"] if r["called"] else None
    if cid:
        d = c.get(f"/api/tickets/{cid}?viewer=t3")
        assert d.status_code == 200 and "account" not in d.json()
        assert c.get(f"/api/tickets/{cid}?viewer=t1").status_code == 403
        assert c.get(f"/api/tickets/{cid}?viewer=m1").status_code == 403
        assert c.post(f"/api/tickets/{cid}/complete", json={"user": "t3"}).json()["status"] == "done"
    assert c.post(f"/api/tickets/{t1['called']['ticket_id']}/complete", json={"user": "t3"}).json()["detail"] == "호출 중인 고객이 아닙니다"
    assert c.get("/api/counters/C1/queue?viewer=t2").status_code == 403
    assert c.post("/api/counters/C1/next", json={"user": "m1"}).status_code == 403
    assert c.post("/api/counters/C1/next", json={}).json()["detail"] == "사용자를 확인하세요"
    assert c.post("/api/counters/C9/next", json={"user": "t1"}).status_code == 404
    assert c.get("/api/manager/summary?viewer=t1").status_code == 403
    s = c.get("/api/manager/summary?viewer=m1").text
    assert "김" not in s and "010-" not in s


def test_priority_order():
    ticket("일반", "fx")
    t = ticket("예약", "fx", reserved_at="2026-10-30 15:00").json()
    c.post(f"/api/tickets/{t['ticket_id']}/checkin", json={"at": "2026-10-30 15:05"})
    q = c.get("/api/counters/C4/queue?viewer=t4").json()
    assert q[0]["priority"] is True and q[0]["ticket_id"] == t["ticket_id"]
