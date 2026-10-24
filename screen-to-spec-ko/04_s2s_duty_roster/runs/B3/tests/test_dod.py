import os, sys, itertools
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
import main

c = TestClient(main.app)
M = "2026-11"
UN = {(r["name"], r["date"]) for r in c.get("/api/unavailable?month=" + M).json()}


def gen():
    r = c.post("/api/roster/generate", json={"month": M})
    assert r.status_code == 200, r.text
    return r.json()["days"]


def test_t1():
    r = c.get("/")
    assert r.status_code == 200 and "당직" in r.text


def test_rules():
    days = gen()
    assert len(days) == 30 and all(d["name"] for d in days)             # R1
    assert not any((d["name"], d["date"]) in UN for d in days)          # R2
    names = [d["name"] for d in days]
    assert all(a != b for a, b in zip(names, names[1:]))                # R3
    assert names[0] != "김민수"                                          # 10-31 담당
    st = c.get("/api/stats?month=" + M).json()
    t = [s["total"] for s in st]; w = [s["weekend"] for s in st]
    assert len(st) == 6 and sum(t) == 30
    assert max(t) - min(t) <= 1 and max(w) - min(w) <= 1               # R4 R5


def test_swap_confirm():
    days = gen()
    by = {d["date"]: d["name"] for d in days}
    ok = None
    for a, b in itertools.combinations(by, 2):
        if a == "2026-11-01" or by[a] == by[b]: continue
        r = c.post("/api/roster/swap", json={"date_a": a, "date_b": b})
        if r.status_code == 200:
            ok = (a, b); break
    assert ok
    new = {d["date"]: d["name"] for d in c.get("/api/roster?month=" + M).json()["days"]}
    assert new[ok[0]] == by[ok[1]]
    # 제외일로 보내기
    gen(); by = {d["date"]: d["name"] for d in c.get("/api/roster?month=" + M).json()["days"]}
    other = next(k for k, v in by.items() if v != "박지연" and k > "2026-11-08")
    p = next(k for k, v in by.items() if v == "박지연" and k > "2026-11-08")
    r = c.post("/api/roster/swap", json={"date_a": "2026-11-03", "date_b": p})
    assert r.status_code == 409 and "R2" in r.json()["detail"]
    # 연속 만들기
    ds = sorted(by)
    for i in range(2, 28):
        x = by[ds[i - 1]]
        if by[ds[i + 2]] != x and by[ds[i]] != x:
            pass
    d = ds[10]; far = next(k for k in ds[15:] if by[k] == by[ds[11]] ) if any(by[k] == by[ds[11]] for k in ds[15:]) else None
    if far:
        r = c.post("/api/roster/swap", json={"date_a": d, "date_b": far})
        assert r.status_code == 409 and "R3" in r.json()["detail"]
    assert c.post("/api/roster/swap", json={"date_a": d, "date_b": d}).status_code == 400
    assert c.post("/api/roster/swap", json={"date_a": d, "date_b": "2026-12-05"}).status_code == 400
    assert c.post("/api/roster/confirm", json={"month": "2026-12"}).status_code == 400
    assert c.post("/api/roster/confirm", json={"month": M}).status_code == 200
    assert c.post("/api/roster/generate", json={"month": M}).status_code == 409
    by = {d["date"]: d["name"] for d in c.get("/api/roster?month=" + M).json()["days"]}
    for a, b in itertools.combinations(sorted(by), 2):
        if by[a] != by[b] and c.post("/api/roster/swap", json={"date_a": a, "date_b": b}).status_code == 200:
            break
    else:
        raise AssertionError("no swap after confirm")
