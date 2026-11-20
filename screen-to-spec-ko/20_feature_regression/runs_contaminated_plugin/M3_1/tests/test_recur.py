# -*- coding: utf-8 -*-
"""v2 새 완료 기준 T10~T12 (반복 예약). test_dod.py 의 서버 · 고정 데이터를 그대로 쓴다."""
import urllib.parse

from test_dod import srv, pw, http, open_page, select_user, slot, DATE  # noqa: F401

D = ["2026-12-01", "2026-12-08", "2026-12-15", "2026-12-22"]


def day(s, d, room=None):
    st, data = http("GET", s.base + "/api/reservations?date=" + d)
    assert st == 200
    return [r for r in data if room is None or r["room_id"] == room]


def rep(s, room, d, weeks, user="박지연", start="09:00", end="10:00"):
    body = {"room_id": room, "date": d, "start": start, "end": end, "user": user}
    if weeks is not None:
        body["repeat_weeks"] = weeks
    return http("POST", s.base + "/api/reservations", body)


def delete(s, rid, user, scope=None):
    q = "?user=" + urllib.parse.quote(user) + ("&scope=" + scope if scope else "")
    return http("DELETE", s.base + "/api/reservations/%d%s" % (rid, q))[0]


def test_T10_repeat_all_or_nothing(srv):
    st, body = rep(srv, "B", "2026-11-17", 3)
    assert st == 201 and len(body["reservations"]) == 3 and body["series_id"]
    assert [r["date"] for r in body["reservations"]] == ["2026-11-17", "2026-11-24", "2026-12-01"]
    for d in ("2026-11-17", "2026-11-24", "2026-12-01"):
        assert len(day(srv, d, "B")) == 1
    assert rep(srv, "A", "2027-01-12", None)[0] == 201
    assert rep(srv, "A", "2027-01-19", None, start="09:30", end="10:30")[0] == 201  # 둘째 주를 미리 채움
    st, body = rep(srv, "A", "2027-01-12", 3)
    assert st == 409 and body["detail"] == "반복 예약 중 겹치는 날짜가 있습니다"
    assert len(day(srv, "2027-01-12")) == 1 and len(day(srv, "2027-01-26")) == 0


def test_T11_cancel_scope(srv):
    st, body = rep(srv, "C", D[0], 4, user="김민수")
    ids = [r["res_id"] for r in body["reservations"]]
    assert delete(srv, ids[0], "박지연", "following") == 403
    assert all(len(day(srv, d, "C")) == 1 for d in D)
    assert delete(srv, ids[1], "김민수", "one") == 204
    assert [len(day(srv, d, "C")) for d in D] == [1, 0, 1, 1]
    assert delete(srv, ids[2], "김민수", "following") == 204
    assert [len(day(srv, d, "C")) for d in D] == [1, 0, 0, 0]


def test_T12_repeat_range(srv):
    for w in (1, 9, 0, -1, "abc"):
        st, body = rep(srv, "B", "2027-02-02", w)
        assert st == 400 and body["detail"] == "반복은 2주에서 8주까지 가능합니다", w
    assert len(day(srv, "2027-02-02")) == 0
    st, body = rep(srv, "B", "2027-02-02", 8)
    assert st == 201 and len(body["reservations"]) == 8


def test_ui_repeat(srv, pw):
    page = open_page(pw, srv)
    select_user(page, "한도윤")
    slot(page, "C", "09:00").click()
    page.select_option('[data-testid="repeat-select"]', label="3주")
    page.click("#submit")
    page.wait_for_timeout(800)
    el = slot(page, "C", "09:00")
    assert el.get_attribute("data-state") == "mine"
    assert el.query_selector('[data-testid="cancel-following-btn"]') is not None
    el.query_selector('[data-testid="cancel-following-btn"]').click()
    page.wait_for_timeout(800)
    assert slot(page, "C", "09:00").get_attribute("data-state") == "free"
    page.close()
