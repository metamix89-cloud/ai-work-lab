import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main  # noqa: E402


@pytest.fixture()
def c():
    main.init_db()
    return TestClient(main.app)


def finish_lessons(c, user):
    for lid in ("L1", "L2", "L3", "L4"):
        c.post(f"/api/lessons/{lid}/complete", json={"user": user})


def test_t1_home(c):
    r = c.get("/")
    assert r.status_code == 200 and "온보딩" in r.text


def test_t2_quiz_no_answer(c):
    qs = c.get("/api/quiz").json()
    assert len(qs) == 5 and all("answer" not in q and len(q["choices"]) == 4 for q in qs)


def test_t3_order(c):
    r = c.post("/api/lessons/L4/complete", json={"user": "김신입"})
    assert r.status_code == 409 and r.json()["detail"] == "이전 레슨을 먼저 마치세요"
    assert c.post("/api/lessons/L1/complete", json={"user": "김신입"}).status_code == 200  # 이미 완료
    r = c.post("/api/lessons/L3/complete", json={"user": "김신입"})
    assert r.status_code == 200 and r.json()["progress"] == 75


def test_t4_quiz_early(c):
    r = c.post("/api/quiz/submit", json={"user": "김신입", "answers": [0] * 5})
    assert r.status_code == 409 and r.json()["detail"] == "레슨을 모두 마친 뒤 응시할 수 있습니다"


def answers_for(n_correct):
    right = [1, 1, 2, 1, 2]
    return [a if i < n_correct else (a + 1) % 4 for i, a in enumerate(right)]


def test_t5_pass(c):
    finish_lessons(c, "김신입")
    r = c.post("/api/quiz/submit", json={"user": "김신입", "answers": answers_for(4)})
    assert r.status_code == 200
    body = r.json()
    assert body == {"score": 80, "passed": True, "attempt": 1, "attempts_left": 0, "certified": True}
    assert c.post("/api/quiz/submit", json={"user": "김신입", "answers": answers_for(4)}).status_code == 409


def test_t6_three_fails(c):
    finish_lessons(c, "김신입")
    for _ in range(3):
        assert c.post("/api/quiz/submit", json={"user": "김신입", "answers": answers_for(0)}).status_code == 200
    r = c.post("/api/quiz/submit", json={"user": "김신입", "answers": answers_for(5)})
    assert r.status_code == 409 and r.json()["detail"] == "더 응시할 수 없습니다"
    p = c.get("/api/progress?user=김신입&viewer=김신입").json()
    assert not p["certified"] and p["attempts_left"] == 0


def test_t7_permissions(c):
    assert c.get("/api/progress?user=김신입&viewer=이열심").status_code == 403
    assert c.get("/api/progress?user=김신입&viewer=김신입").status_code == 200
    assert c.get("/api/progress?user=김신입&viewer=최인사").status_code == 200
    assert c.get("/api/admin/incomplete?viewer=김신입").status_code == 403
    assert c.post("/api/quiz/submit", json={"user": "없음", "answers": [9]}).status_code == 400
    assert c.post("/api/quiz/submit", json={"user": "없음", "answers": [0] * 5}).status_code == 404


def test_t8_incomplete(c):
    rows = c.get("/api/admin/incomplete?viewer=최인사").json()
    assert [r["user"] for r in rows] == ["김신입", "이열심"]
    assert [r["progress"] for r in rows] == [50, 100]
