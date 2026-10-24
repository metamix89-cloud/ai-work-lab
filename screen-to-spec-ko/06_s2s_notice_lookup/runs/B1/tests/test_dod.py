import sys
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from main import app  # noqa: E402

c = TestClient(app)


def items(**p):
    return c.get("/api/notices", params=p).json()["items"]


def test_t1_index():
    r = c.get("/")
    assert r.status_code == 200 and "고시" in r.text


def test_t2_default_hides_repealed_and_no_link():
    assert len(items()) == 7


def test_t3_upcoming():
    up = [i for i in items() if i["status"] == "시행 예정"]
    assert len(up) == 2
    for i in up:
        assert i["days_until"] == (date.fromisoformat(i["effective_from"]) - date.today()).days


def test_t4_include_repealed():
    its = items(include_repealed="1")
    assert len(its) == 9 and sum(i["status"] == "폐지" for i in its) == 2
    assert "N010" not in {i["notice_id"] for i in its}


def test_t5_no_summary():
    no = [i for i in items() if not i["has_summary"]]
    assert len(no) == 2 and all(i["summary"] == "" for i in no)


def test_t6_fields():
    d = c.get("/api/notices").json()
    assert d["as_of"] == date.today().isoformat()
    for i in d["items"]:
        assert i["issuer"] and i["published"] and i["effective_from"] and i["source_url"].startswith("http")


def test_t7_and_and_sort():
    its = items(category="위생", q="위생 점검")
    assert {i["notice_id"] for i in its} == {"N004", "N005"}
    all_ = items()
    keys = [(-int(i["published"].replace("-", "")), i["notice_id"]) for i in all_]
    assert keys == sorted(keys)


def test_t8_rejections():
    assert c.get("/api/notices", params={"category": "없음"}).status_code == 400
    assert c.get("/api/notices", params={"include_repealed": "2"}).status_code == 400
    assert c.get("/api/notices/N999").status_code == 404
    assert c.get("/api/notices/N010").status_code == 404
