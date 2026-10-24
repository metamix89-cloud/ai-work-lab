from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def new(user, typ, s, e):
    return c.post("/api/requests", json={"user": user, "type": typ, "start": s, "end": e, "reason": "x"})


def test_flow():
    assert c.get("/api/balance?user=박지연").json() == {"total": 15, "used": 2, "pending": 1, "remaining": 12}
    r = new("박지연", "연차", "2026-11-05", "2026-11-09")
    assert r.status_code == 201 and r.json()["days"] == 3
    assert new("박지연", "연차", "2026-11-06", "2026-11-06").status_code == 409
    assert new("이수진", "연차", "2026-12-01", "2027-01-30").status_code == 400
    assert new("이수진", "출장", "2026-12-01", "2027-01-30").status_code == 201
    rid = r.json()["req_id"]
    assert c.post(f"/api/requests/{rid}/approve", json={"approver": "이수진"}).status_code == 403
    assert c.post(f"/api/requests/{rid}/approve", json={"approver": "김민수"}).json()["status"] == "승인"
    assert c.post(f"/api/requests/{rid}/reject", json={"approver": "김민수", "reason": "a"}).status_code == 409
    assert c.get("/api/balance?user=박지연").json()["remaining"] == 9
    assert c.post("/api/requests/3/reject", json={"approver": "김민수", "reason": ""}).status_code == 400
    assert c.post("/api/requests/3/reject", json={"approver": "김민수", "reason": "마감"}).status_code == 200
    assert new("이수진", "연차", "2026-11-16", "2026-11-17").status_code == 201
    assert [x["user"] for x in c.get("/api/requests?approver=정하윤").json()] == ["최동현"]
    assert c.get("/").status_code == 200
