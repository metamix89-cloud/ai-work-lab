import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi.testclient import TestClient
import main

c = TestClient(main.app)


def get(u):
    return c.get(u)


def items(qs=""):
    return get("/api/notices?" + qs).json()


def test_t1():
    r = get("/")
    assert r.status_code == 200 and "고시" in r.text


def test_t2():
    d = items()
    assert d["count"] == 7 and all(i["status"] != "폐지" for i in d["items"])


def test_t3():
    up = [i for i in items()["items"] if i["status"] == "시행 예정"]
    assert len(up) == 2
    for i in up:
        assert i["days_until"] == (date.fromisoformat(i["effective_from"]) - date.today()).days


def test_t4():
    d = items("include_repealed=1")
    assert d["count"] == 9 and sum(i["status"] == "폐지" for i in d["items"]) == 2
    assert "N006" not in [i["notice_id"] for i in d["items"]]


def test_t5():
    e = [i for i in items()["items"] if not i["has_summary"]]
    assert len(e) == 2 and all(i["summary"] == "" for i in e)


def test_t6():
    d = items()
    assert d["as_of"] == date.today().isoformat()
    for i in d["items"]:
        assert i["issuer"] and i["published"] and i["effective_from"]
        assert i["source_url"].startswith("http")


def test_t7():
    d = items("category=위생&q=점검 음식점")
    assert [i["notice_id"] for i in d["items"]] == ["N004"]
    pubs = [i["published"] for i in items()["items"]]
    assert pubs == sorted(pubs, reverse=True)


def test_t8():
    assert get("/api/notices?category=없음").status_code == 400
    assert get("/api/notices?include_repealed=2").status_code == 400
    assert get("/api/notices/N999").status_code == 404
    assert get("/api/notices/N006").status_code == 404
    assert get("/api/notices/N003").status_code == 200
    r = get("/api/notices?category=없음&include_repealed=2")
    assert r.status_code == 400 and "detail" in r.json()
