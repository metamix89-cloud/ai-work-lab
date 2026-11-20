# -*- coding: utf-8 -*-
"""T10~T12 (PRD 10, v2). test_dod.py 의 서버 · 고정 데이터를 재사용한다.
참고: 이 환경에서는 서버가 요청 약 45~60번 뒤 멈춘다(v1 코드인 /api/rooms 만 불러도 그렇다). 그래서 요청 수를 아꼈다."""
import urllib.request
from datetime import date, timedelta

from test_dod import srv, http, DATE, pw, open_page, select_user, slot  # noqa: F401


def q(s):
    return urllib.request.quote(s)


def rec(s, room, start, end, weeks, user="박지연", d=DATE):
    return http("POST", s.base + "/api/reservations",
                {"room_id": room, "date": d, "start": start, "end": end, "user": user, "repeat_weeks": weeks})


def dates(n, d=DATE):
    b = date.fromisoformat(d)
    return [(b + timedelta(days=7 * i)).isoformat() for i in range(n)]


def count(s, room, start, ds):
    n = 0
    for d in ds:
        st, data = http("GET", s.base + "/api/reservations?date=" + d)
        n += sum(1 for r in data if r["room_id"] == room and r["start"] == start)
    return n


def test_ui_repeat(srv, pw):
    page = open_page(pw, srv)
    select_user(page, "정하늘")
    slot(page, "A", "15:00").click()
    page.select_option('[data-testid="repeat-select"]', label="2주")
    page.click("#submit")
    page.wait_for_timeout(800)
    s = slot(page, "A", "15:00")
    assert s.get_attribute("data-state") == "mine"
    assert s.query_selector('[data-testid="cancel-following-btn"]') is not None
    assert slot(page, "A", "10:00").query_selector('[data-testid="cancel-following-btn"]') is None
    page.close()


def test_T10(srv):
    st, b = rec(srv, "A", "09:00", "09:30", 3)
    assert st == 201 and len(b["reservations"]) == 3 and b["series_id"]
    assert [r["date"] for r in b["reservations"]] == dates(3)
    # 둘째 주(11-10) C 12:00 를 미리 잡고 같은 시간 반복 → 409, 전무
    assert http("POST", srv.base + "/api/reservations", {"room_id": "C", "date": dates(2)[1], "start": "12:00",
                                                         "end": "12:30", "user": "김민수"})[0] == 201
    st, b = rec(srv, "C", "12:00", "12:30", 3)
    assert st == 409 and b["detail"] == "반복 예약 중 겹치는 날짜가 있습니다"
    assert count(srv, "C", "12:00", dates(3)) == 1


def test_T11(srv):
    st, b = rec(srv, "B", "17:00", "17:30", 4)
    ids = [r["res_id"] for r in b["reservations"]]
    base = srv.base + "/api/reservations/%d?user=%s&scope=%s"
    assert http("DELETE", base % (ids[0], q("김민수"), "following"))[0] == 403
    assert count(srv, "B", "17:00", dates(4)) == 4
    assert http("DELETE", base % (ids[1], q("박지연"), "one"))[0] == 204
    assert count(srv, "B", "17:00", dates(4)) == 3
    assert http("DELETE", base % (ids[2], q("박지연"), "following"))[0] == 204
    assert count(srv, "B", "17:00", dates(4)) == 1
    assert count(srv, "B", "17:00", dates(1)) == 1


def test_T12(srv):
    for w in (1, 9, 0, "abc", -1):
        assert rec(srv, "C", "09:00", "09:30", w)[0] == 400
    assert count(srv, "C", "09:00", dates(2)) == 0
    st, b = rec(srv, "C", "09:00", "09:30", 8)
    assert st == 201 and count(srv, "C", "09:00", dates(8)) == 8
