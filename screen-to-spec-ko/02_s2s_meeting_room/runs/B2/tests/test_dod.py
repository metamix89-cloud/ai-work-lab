import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import main

D = "2026-11-03"
def client():
    main.init_db()
    return TestClient(main.app)
def post(c, s, e, room="C", user="박지연", d=D):
    return c.post("/api/reservations", json={"room_id": room, "date": d, "start": s, "end": e, "user": user})
def count(c): return len(c.get(f"/api/reservations?date={D}").json())

def test_t1(): r = client().get("/"); assert r.status_code == 200 and "회의실" in r.text
def test_t4():
    c = client(); n = count(c); assert post(c, "10:30", "11:30", "A").status_code == 409; assert count(c) == n
def test_t5(): c = client(); assert post(c, "11:00", "12:00", "A").status_code == 201 and post(c, "10:00", "11:00", "A", d="2026-11-04").status_code == 201
def test_t6(): c = client(); assert post(c, "10:15", "11:00").status_code == 400; assert post(c, "17:30", "18:30").status_code == 400
def test_t7(): c = client(); assert post(c, "13:00", "15:30").status_code == 400; assert post(c, "13:00", "15:00").status_code == 201
def test_t8():
    c = client()
    assert c.delete("/api/reservations/1?user=박지연").status_code == 403 and count(c) == 5
    assert c.delete("/api/reservations/1?user=김민수").status_code == 204 and count(c) == 4
