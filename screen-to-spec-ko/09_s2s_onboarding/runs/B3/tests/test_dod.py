import os
import subprocess
import sys
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import main  # noqa: E402


@pytest.fixture()
def c():
    main.reset_db()
    return TestClient(main.app)


def complete(c, user, lid):
    return c.post(f"/api/lessons/{lid}/complete", json={"user": user})


def finish_lessons(c, user):
    for lid in ("L1", "L2", "L3", "L4"):
        complete(c, user, lid)


def test_t1_home(c):
    r = c.get("/")
    assert r.status_code == 200 and "온보딩" in r.text


def test_t2_quiz_no_answer(c):
    q = c.get("/api/quiz").json()
    assert len(q) == 5
    for x in q:
        assert set(x) == {"q_id", "text", "choices"} and len(x["choices"]) == 4


def test_t3_order(c):
    assert complete(c, "김신입", "L4").status_code == 409
    assert complete(c, "김신입", "L2").status_code == 200  # 이미 마침 -> 변화 없음
    r = complete(c, "김신입", "L3")
    assert r.status_code == 200 and r.json()["progress"] == 75
    assert complete(c, "김신입", "L3").status_code == 200


def test_t4_quiz_before_lessons(c):
    r = c.post("/api/quiz/submit", json={"user": "김신입", "answers": [0] * 5})
    assert r.status_code == 409 and r.json()["detail"] == "레슨을 모두 마친 뒤 응시할 수 있습니다"


def test_t5_pass(c):
    finish_lessons(c, "김신입")
    key = [1, 1, 2, 1, 1]
    r = c.post("/api/quiz/submit", json={"user": "김신입", "answers": [1, 1, 2, 1, 0]})
    assert r.status_code == 200
    body = r.json()
    assert body == {"score": 80, "passed": True, "attempt": 1, "attempts_left": 2, "certified": True}
    assert c.post("/api/quiz/submit", json={"user": "김신입", "answers": key}).status_code == 409
    assert c.get("/api/progress?user=김신입&viewer=김신입").json()["certified"] is True


def test_t6_three_fails(c):
    finish_lessons(c, "김신입")
    for _ in range(3):
        assert c.post("/api/quiz/submit", json={"user": "김신입", "answers": [0] * 5}).status_code == 200
    r = c.post("/api/quiz/submit", json={"user": "김신입", "answers": [1, 1, 2, 1, 1]})
    assert r.status_code == 409 and r.json()["detail"] == "더 응시할 수 없습니다"
    assert c.get("/api/progress?user=김신입&viewer=최인사").json()["certified"] is False


def test_t7_permissions(c):
    assert c.get("/api/progress?user=이진행&viewer=김신입").status_code == 403
    assert c.get("/api/progress?user=김신입&viewer=김신입").status_code == 200
    assert c.get("/api/progress?user=김신입&viewer=최인사").status_code == 200
    assert c.get("/api/admin/incomplete?viewer=김신입").status_code == 403
    assert c.post("/api/quiz/submit", json={"user": "없는이", "answers": [0]}).status_code == 400
    assert c.post("/api/quiz/submit", json={"user": "없는이", "answers": [0] * 5}).status_code == 404


def test_t8_incomplete(c):
    rows = c.get("/api/admin/incomplete?viewer=최인사").json()
    assert [r["user"] for r in rows] == ["김신입", "이진행"]
    assert [r["progress"] for r in rows] == [50, 100]


@pytest.fixture(scope="module")
def server():
    pytest.importorskip("playwright")
    env = dict(os.environ, PORT="8765")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", "8765"], cwd=ROOT, env=env)
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/")
            break
        except Exception:
            time.sleep(0.2)
    yield "http://127.0.0.1:8765"
    p.terminate()


def test_t9_ui(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.goto(server)
        page.select_option('[data-testid="user-select"]', "김신입")
        page.wait_for_selector('[data-testid="lesson"]')
        states = [l.get_attribute("data-state") for l in page.query_selector_all('[data-testid="lesson"]')]
        assert states == ["done", "done", "open", "locked"]
        assert page.inner_text('[data-testid="progress"]').strip() == "50%"
        assert page.query_selector('[data-testid="quiz"]') is None
        page.select_option('[data-testid="user-select"]', "최인사")
        page.wait_for_selector('[data-testid="incomplete-row"]')
        assert page.query_selector('[data-testid="lesson"]') is None
        b.close()
