import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from datetime import date, timedelta
from fastapi.testclient import TestClient
import main

c = TestClient(main.app)
M = "2026-11"


def gen():
    r = c.post("/api/roster/generate", json={"month": M})
    assert r.status_code == 200, r.text
    return r.json()


def test_t1():
    r = c.get("/")
    assert r.status_code == 200 and "당직" in r.text


def test_rules():
    days = gen()["days"]
    names = [d["name"] for d in days]
    assert len(days) == 30 and all(names)
    un = c.get("/api/unavailable", params={"month": M}).json()
    for u in un:
        assert next(d for d in days if d["date"] == u["date"])["name"] != u["name"]
    assert all(a != b for a, b in zip(names, names[1:]))
    assert names[0] != "김민수"  # 10-31 당직자
    st = c.get("/api/stats", params={"month": M}).json()
    t = [s["total"] for s in st]; w = [s["weekend"] for s in st]
    assert max(t) - min(t) <= 1 and max(w) - min(w) <= 1 and sum(t) == 30


def test_swap_and_confirm():
    days = gen()["days"]
    by = {d["date"]: d["name"] for d in days}
    # 연속을 만드는 바꾸기: 11-10 과 이웃 당직자를 가진 날
    bad = None
    for a in by:
        for b in by:
            if a < b and by[a] != by[b]:
                nb = [(date.fromisoformat(b) + timedelta(days=k)).isoformat() for k in (-1, 1)]
                if by[a] in [by.get(x) for x in nb if x != a]:
                    bad = (a, b); break
        if bad: break
    assert bad and c.post("/api/roster/swap", json={"date_a": bad[0], "date_b": bad[1]}).status_code == 409
    # 제외일: 박지연 -> 11-03
    d3 = by["2026-11-03"]
    other = next(k for k, v in by.items() if v == "박지연")
    r = c.post("/api/roster/swap", json={"date_a": "2026-11-03", "date_b": other})
    assert r.status_code == 409 and "R2" in r.json()["detail"]
    assert c.post("/api/roster/swap", json={"date_a": "2026-11-03", "date_b": "2026-11-03"}).status_code == 400
    assert c.post("/api/roster/confirm", json={"month": M}).status_code == 200
    assert c.post("/api/roster/generate", json={"month": M}).status_code == 409
    assert c.post("/api/roster/confirm", json={"month": "2026-12"}).status_code == 400
