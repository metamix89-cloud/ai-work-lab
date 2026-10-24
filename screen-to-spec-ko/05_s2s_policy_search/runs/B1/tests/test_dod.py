import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi.testclient import TestClient

from main import app

c = TestClient(app)


def ids(q):
    return [r["clause_id"] for r in c.get("/api/search", params={"q": q}).json()["results"]]


def test_t1():
    r = c.get("/")
    assert r.status_code == 200 and "규정" in r.text


def test_t2():
    assert ids("연차 이월") == ["L-07"]


def test_t3():
    for r in c.get("/api/search", params={"q": "연차"}).json()["results"]:
        assert r["doc"] and r["article"] and r["effective_from"]


def test_t4():
    d = c.get("/api/search", params={"q": "헬스장"}).json()
    assert d["count"] == 0 and d["results"] == []


def test_t5():
    assert ids("출장 숙박비 해외") == ["T-05"]


def test_t6():
    h = c.get("/api/clauses/L-07/history").json()
    assert h[0]["clause_id"] == "L-07v1" and h[0]["effective_to"]


def test_t7():
    assert c.get("/api/search", params={"q": "  "}).status_code == 400
    assert c.get("/api/clauses/X-99").status_code == 404


def test_t8():
    assert ids("재택") == ["W-01", "W-03"]
