# -*- coding: utf-8 -*-
"""v2 새 완료 기준 T10~T12. 서버는 테스트가 띄운다 (PORT 환경 변수, 기본 8766)."""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

import pytest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("PORT", "8766"))
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + urllib.parse.quote(path, safe="/?&=:"), data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


@pytest.fixture(scope="module", autouse=True)
def server():
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT)], cwd=APP,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/api/rooms")
            break
        except Exception:
            time.sleep(0.2)
    yield
    p.terminate()
    p.wait()


def dates(room, days):
    out = []
    for d in days:
        out += [r for r in call("GET", f"/api/reservations?date={d}")[1] if r["room_id"] == room]
    return out


def body(**kw):
    b = {"room_id": "C", "date": "2027-03-01", "start": "09:00", "end": "10:00", "user": "박지연"}
    b.update(kw)
    return b


def test_t10():
    st, r = call("POST", "/api/reservations", body(repeat_weeks=3))
    assert st == 201 and len(r["reservations"]) == 3
    assert [x["date"] for x in r["reservations"]] == ["2027-03-01", "2027-03-08", "2027-03-15"]
    assert call("POST", "/api/reservations", body(room_id="B", date="2027-03-08"))[0] == 201
    st, r = call("POST", "/api/reservations", body(room_id="B", repeat_weeks=3))
    assert st == 409 and r["detail"] == "반복 예약 중 겹치는 날짜가 있습니다"
    assert len(dates("B", ["2027-03-01", "2027-03-15"])) == 0


def test_t11():
    st, r = call("POST", "/api/reservations", body(date="2027-04-05", repeat_weeks=4))
    ids = [x["res_id"] for x in r["reservations"]]
    days = ["2027-04-05", "2027-04-12", "2027-04-19", "2027-04-26"]
    assert call("DELETE", f"/api/reservations/{ids[1]}?user=김민수&scope=following")[0] == 403
    assert len(dates("C", days)) == 4
    assert call("DELETE", f"/api/reservations/{ids[1]}?user=박지연&scope=one")[0] == 204
    assert sorted(x["res_id"] for x in dates("C", days)) == [ids[0], ids[2], ids[3]]
    assert call("DELETE", f"/api/reservations/{ids[2]}?user=박지연&scope=following")[0] == 204
    assert [x["res_id"] for x in dates("C", days)] == [ids[0]]


def test_t12():
    for bad in (1, 9, 0, "abc", -1):
        assert call("POST", "/api/reservations", body(date="2027-05-03", repeat_weeks=bad))[0] == 400
    days = [f"2027-05-{d:02d}" for d in (3, 10, 17, 24, 31)] + ["2027-06-07", "2027-06-14", "2027-06-21"]
    assert dates("C", days) == []
    st, r = call("POST", "/api/reservations", body(date="2027-05-03", repeat_weeks=8))
    assert st == 201 and len(dates("C", days)) == 8
