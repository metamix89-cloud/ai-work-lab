# -*- coding: utf-8 -*-
"""v2 완료 기준 T10~T12 (반복 예약). test_dod.py 의 서버 도우미를 그대로 쓴다."""
import subprocess
import urllib.request

import pytest

from test_dod import Server, http, PORT, DATE, open_page, select_user, slot

Q = urllib.request.quote
D = ["2026-12-01", "2026-12-08", "2026-12-15", "2026-12-22"]


@pytest.fixture(scope="module")
def srv():
    # 서버 로그를 읽는 쪽이 없으니 파이프가 차서 서버가 멈춘다 — 로그를 버린다
    real = subprocess.Popen
    subprocess.Popen = lambda *a, **k: real(*a, **{**k, "stdout": subprocess.DEVNULL})
    try:
        s = Server(PORT).start()
    finally:
        subprocess.Popen = real
    yield s
    s.stop()


def day(s, d):
    return http("GET", s.base + "/api/reservations?date=" + d)[1]


def rec(s, room, date, weeks, user="박지연", start="09:00", end="10:00"):
    return http("POST", s.base + "/api/reservations",
                {"room_id": room, "date": date, "start": start, "end": end, "user": user, "repeat_weeks": weeks})


def test_T10_repeat_all_or_nothing(srv):
    st, b = rec(srv, "A", "2026-11-03", 3)
    assert st == 201 and len(b["reservations"]) == 3 and b["series_id"]
    for d in ("2026-11-03", "2026-11-10", "2026-11-17"):
        assert any(r["start"] == "09:00" and r["room_id"] == "A" and r["series_id"] == b["series_id"] for r in day(srv, d))
    http("POST", srv.base + "/api/reservations", {"room_id": "B", "date": "2026-12-08", "start": "11:00", "end": "12:00", "user": "김민수"})
    st, b = rec(srv, "B", "2026-12-01", 3, start="11:30", end="12:30")
    assert st == 409 and b["detail"] == "반복 예약 중 겹치는 날짜가 있습니다"
    for d in ("2026-12-01", "2026-12-15"):
        assert not any(r["room_id"] == "B" and r["start"] == "11:30" for r in day(srv, d))


def test_T11_cancel_scopes(srv):
    st, b = rec(srv, "C", D[0], 4, user="김민수", start="13:00", end="14:00")
    ids = [r["res_id"] for r in b["reservations"]]
    st, _ = http("DELETE", srv.base + "/api/reservations/%d?user=%s&scope=following" % (ids[1], Q("박지연")))
    assert st == 403 and sum(len(day(srv, d)) > 0 and any(r["res_id"] in ids for r in day(srv, d)) for d in D) == 4
    st, _ = http("DELETE", srv.base + "/api/reservations/%d?user=%s&scope=one" % (ids[1], Q("김민수")))
    assert st == 204
    left = lambda: {r["res_id"] for d in D for r in day(srv, d) if r["res_id"] in ids}
    assert left() == {ids[0], ids[2], ids[3]}
    st, _ = http("DELETE", srv.base + "/api/reservations/%d?user=%s&scope=following" % (ids[2], Q("김민수")))
    assert st == 204 and left() == {ids[0]}


def test_T12_repeat_weeks_range(srv):
    import datetime
    days = [(datetime.date(2027, 1, 4) + datetime.timedelta(days=7 * i)).isoformat() for i in range(9)]  # 8주 + 1주 여분

    def count():
        return sum(len(day(srv, d)) for d in days)
    for bad in (1, 9, 0, -1, "abc"):
        st, _ = rec(srv, "A", "2027-01-04", bad)
        assert st == 400, bad
    assert count() == 0
    st, b = rec(srv, "A", "2027-01-04", 8)
    assert st == 201 and len(b["reservations"]) == 8 and count() == 8


def test_ui_repeat(srv, pw):
    page = open_page(pw, srv)
    page.fill('[data-testid="date"]', "2026-12-29")
    page.dispatch_event('[data-testid="date"]', "change")
    page.wait_for_timeout(500)
    select_user(page, "박지연")
    slot(page, "A", "15:00").click()
    page.select_option('[data-testid="repeat-select"]', label="2주")
    page.click("#submit")
    page.wait_for_timeout(800)
    cell = slot(page, "A", "15:00")
    assert cell.get_attribute("data-state") == "mine"
    assert cell.query_selector('[data-testid="cancel-following-btn"]')
    assert slot(page, "A", "09:00").query_selector('[data-testid="cancel-following-btn"]') is None
    page.close()


@pytest.fixture(scope="module")
def pw():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()
