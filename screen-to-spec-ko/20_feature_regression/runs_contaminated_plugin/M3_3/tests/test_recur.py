# T10~T12 (v2). test_dod.py 의 서버 도우미를 빌려 쓴다.
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dod import http, srv  # noqa: E402,F401  (srv 는 fixture)


def body(**kw):
    b = {"room_id": "C", "date": "2026-12-01", "start": "09:00", "end": "10:00", "user": "박지연"}
    b.update(kw)
    return b


def day(s, d):
    return http("GET", s.base + "/api/reservations?date=" + d)[1]


def post(s, **kw):
    return http("POST", s.base + "/api/reservations", body(**kw))


def test_T10(srv):
    st, r = post(srv, room_id="B", repeat_weeks=3)
    assert st == 201 and len(r["reservations"]) == 3
    assert [x["date"] for x in r["reservations"]] == ["2026-12-01", "2026-12-08", "2026-12-15"]
    assert post(srv, room_id="A", date="2026-12-08")[0] == 201
    st, r = post(srv, room_id="A", repeat_weeks=3)
    assert st == 409 and r["detail"] == "반복 예약 중 겹치는 날짜가 있습니다"
    for d in ("2026-12-01", "2026-12-15"):
        assert all(x["room_id"] != "A" for x in day(srv, d))


def test_T11(srv):
    st, r = post(srv, date="2027-01-05", repeat_weeks=4)
    assert st == 201
    ids = [x["res_id"] for x in r["reservations"]]
    dates = [x["date"] for x in r["reservations"]]

    def alive():
        return [x["res_id"] for d in dates for x in day(srv, d) if x["res_id"] in ids]

    def delete(i, user, scope):
        return http("DELETE", srv.base + "/api/reservations/%d?user=%s&scope=%s" % (i, urllib.parse.quote(user), scope))[0]

    assert delete(ids[1], "김민수", "following") == 403
    assert len(alive()) == 4
    assert delete(ids[1], "박지연", "one") == 204
    assert alive() == [ids[0], ids[2], ids[3]]
    assert delete(ids[2], "박지연", "following") == 204
    assert alive() == [ids[0]]


def test_T12(srv):
    for w in (1, 9, 0, "abc", -1, True):
        st, r = post(srv, date="2027-03-02", repeat_weeks=w)
        assert st == 400 and r["detail"] == "반복은 2주에서 8주까지 가능합니다", w
    assert day(srv, "2027-03-02") == [] and day(srv, "2027-03-09") == []
    st, r = post(srv, date="2027-04-06", repeat_weeks=8)
    assert st == 201 and len(r["reservations"]) == 8
