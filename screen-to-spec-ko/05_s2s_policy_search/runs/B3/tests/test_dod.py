"""API 수준 완료 기준 확인 (T1~T8). 화면 T9 는 브라우저로 확인한다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

c = TestClient(app)


def ids(q):
    return [r["clause_id"] for r in c.get("/api/search", params={"q": q}).json()["results"]]


def test_t1_index():
    r = c.get("/")
    assert r.status_code == 200 and "규정" in r.text


def test_t2_current_only():
    assert ids("연차 이월") == ["L-07"]


def test_t3_evidence():
    for r in c.get("/api/search", params={"q": "연차"}).json()["results"]:
        assert r["doc"] and r["article"] and r["effective_from"]


def test_t4_none():
    d = c.get("/api/search", params={"q": "헬스장"}).json()
    assert d["count"] == 0 and d["results"] == []


def test_t5_and():
    assert ids("출장 숙박비 해외") == ["T-03"]


def test_t6_history():
    h = c.get("/api/clauses/L-07/history").json()
    assert [x["clause_id"] for x in h] == ["L-07v1"] and h[0]["effective_to"]
    assert c.get("/api/clauses/L-05/history").json() == []


def test_t7_rejects():
    r = c.get("/api/search", params={"q": "  "})
    assert r.status_code == 400 and r.json() == {"detail": "검색어를 입력하세요"}
    assert c.get("/api/clauses/X-99").status_code == 404


def test_t8_order():
    assert ids("재택") == ["W-01", "W-04"]


def test_docs_and_snippet():
    docs = {d["doc"]: d["count"] for d in c.get("/api/docs").json()}
    assert docs == {"연차 규정": 5, "출장 규정": 3, "재택 규정": 2}
    s = c.get("/api/search", params={"q": "이월"}).json()["results"][0]["snippet"]
    assert "<mark>이월</mark>" in s
