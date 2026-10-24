"""API 기준 완료 기준 확인. 서버를 따로 띄우지 않고 uvicorn 을 하위 프로세스로 실행한다."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module", autouse=True)
def server():
    env = dict(os.environ, PORT=str(PORT))
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT)],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    yield
    p.terminate()


def get(path):
    try:
        with urllib.request.urlopen(BASE + path) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def notices(qs=""):
    status, body = get("/api/notices" + qs)
    assert status == 200
    return json.loads(body)


def test_t1_index():
    status, body = get("/")
    assert status == 200 and "고시" in body


def test_t2_default_list():
    d = notices()
    assert d["count"] == 7
    assert all(i["status"] != "폐지" for i in d["items"])


def test_t3_upcoming():
    ups = [i for i in notices()["items"] if i["status"] == "시행 예정"]
    assert len(ups) == 2
    for i in ups:
        assert i["days_until"] == (date.fromisoformat(i["effective_from"]) - date.today()).days


def test_t4_include_repealed():
    d = notices("?include_repealed=1")
    assert d["count"] == 9
    assert sum(i["status"] == "폐지" for i in d["items"]) == 2


def test_t5_no_summary():
    empty = [i for i in notices("?include_repealed=1")["items"] if not i["has_summary"]]
    assert empty and all(i["summary"] == "" for i in empty)


def test_t6_fields():
    d = notices("?include_repealed=1")
    assert d["as_of"] == date.today().isoformat()
    for i in d["items"]:
        assert i["issuer"] and i["published"] and i["effective_from"]
        assert i["source_url"].startswith("http")


def test_t7_and_and_sort():
    items = notices()["items"]
    assert [i["published"] for i in items] == sorted((i["published"] for i in items), reverse=True)
    hits = notices("?category=" + urllib.request.quote("위생") + "&q=" + urllib.request.quote("집단급식소 기록"))["items"]
    assert [i["notice_id"] for i in hits] == ["N004"]


def test_t8_rejections():
    assert get("/api/notices?category=" + urllib.request.quote("없음"))[0] == 400
    assert get("/api/notices?include_repealed=2")[0] == 400
    assert get("/api/notices/NOPE")[0] == 404
    assert get("/api/notices/N009")[0] == 404
    assert get("/api/notices/N006")[0] == 200
    # R7: 400 이 404 보다 먼저
    assert get("/api/notices?include_repealed=x")[0] == 400
