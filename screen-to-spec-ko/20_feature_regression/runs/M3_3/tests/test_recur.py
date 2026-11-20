import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PORT = int(os.environ.get("PORT", "9620")) + 40
B = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module", autouse=True)
def server():
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT)], cwd=APP,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(B + "/api/rooms")
            break
        except Exception:
            time.sleep(0.2)
    yield
    p.terminate()
    p.wait()


def call(m, path, body=None):
    r = urllib.request.Request(B + path, method=m, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json"})
    try:
        x = urllib.request.urlopen(r)
        t = x.read()
        return x.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read()
        return e.code, (json.loads(t) if t else None)


def day(d):
    return call("GET", f"/api/reservations?date={d}")[1]


def mk(room, date, w, user="김민수", s="09:00", e="10:00"):
    b = dict(room_id=room, date=date, start=s, end=e, user=user)
    if w is not None:
        b["repeat_weeks"] = w
    return call("POST", "/api/reservations", b)


def test_t10():
    st, b = mk("C", "2027-01-04", 3)
    assert st == 201 and len(b["reservations"]) == 3
    assert [len(day(d)) for d in ("2027-01-04", "2027-01-11", "2027-01-18")] == [1, 1, 1]
    mk("B", "2027-02-08", None, "박지연")
    assert mk("B", "2027-02-01", 3)[0] == 409
    assert day("2027-02-01") == [] and len(day("2027-02-15")) == 0


def test_t11():
    st, b = mk("A", "2027-03-01", 4)
    ids = [r["res_id"] for r in b["reservations"]]
    assert call("DELETE", f"/api/reservations/{ids[1]}?user=%EB%B0%95%EC%A7%80%EC%97%B0&scope=following")[0] == 403
    assert sum(len(day(d)) for d in ("2027-03-01", "2027-03-08", "2027-03-15", "2027-03-22")) == 4
    assert call("DELETE", f"/api/reservations/{ids[1]}?user=%EA%B9%80%EB%AF%BC%EC%88%98&scope=one")[0] == 204
    assert len(day("2027-03-08")) == 0 and len(day("2027-03-15")) == 1
    assert call("DELETE", f"/api/reservations/{ids[2]}?user=%EA%B9%80%EB%AF%BC%EC%88%98&scope=following")[0] == 204
    assert len(day("2027-03-01")) == 1 and not day("2027-03-15") and not day("2027-03-22")


def test_t12():
    for w in (1, 9, 0, "abc"):
        assert mk("C", "2027-05-03", w)[0] == 400
    assert day("2027-05-03") == []
    st, b = mk("C", "2027-05-03", 8)
    assert st == 201 and len(b["reservations"]) == 8
