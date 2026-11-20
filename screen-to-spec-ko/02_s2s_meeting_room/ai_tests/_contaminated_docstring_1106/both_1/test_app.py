# -*- coding: utf-8 -*-
"""PRD.md 기준 테스트 — API(F5, R1~R7)와 화면(F1, F3, F4, R5, R6)."""
import itertools
from urllib.parse import quote

import pytest

from conftest import DATE, RES, ROOMS, USERS, http

_days = itertools.count(1)


def fresh_date():
    """시드 예약이 없는 새 날짜 — 테스트끼리 서버 상태를 공유해도 섞이지 않게 한다."""
    return "2027-01-%02d" % next(_days)


def body(room="A", date=DATE, start="12:00", end="13:00", user="박지연"):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def post(srv, **kw):
    return http("POST", srv.base + "/api/reservations", body(**kw))


def delete(srv, res_id, user):
    return http("DELETE", "%s/api/reservations/%d?user=%s" % (srv.base, res_id, quote(user)))


def listing(srv, date):
    st, data = http("GET", srv.base + "/api/reservations?date=" + quote(date))
    assert st == 200
    return data


# ---------------------------------------------------------------- 조회 API

def test_rooms_api(srv):
    st, data = http("GET", srv.base + "/api/rooms")
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_list_reservations_seed(srv):
    data = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_list_reservations_other_date_empty(srv):
    assert listing(srv, "2030-01-01") == []


# ---------------------------------------------------------------- 생성 · 규칙

def test_create_returns_201_and_reservation(srv):
    d = fresh_date()
    st, r = post(srv, date=d, start="09:00", end="10:00", user="한도윤")
    assert st == 201
    assert (r["room_id"], r["date"], r["start"], r["end"], r["user"]) == ("A", d, "09:00", "10:00", "한도윤")
    assert "res_id" in r
    assert [x["res_id"] for x in listing(srv, d)] == [r["res_id"]]


def test_r1_start_not_30min_unit(srv):
    d = fresh_date()
    st, r = post(srv, date=d, start="10:15", end="11:00")
    assert st == 400
    assert r["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv, d) == []


def test_r1_end_not_30min_unit(srv):
    d = fresh_date()
    st, r = post(srv, date=d, start="10:00", end="10:45")
    assert st == 400
    assert r["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv, d) == []


@pytest.mark.parametrize("start,end", [("08:30", "09:30"), ("17:30", "18:30"), ("18:00", "18:30"), ("10:00", "10:00"), ("11:00", "10:30")])
def test_r2_outside_hours_or_bad_range(srv, start, end):
    d = fresh_date()
    st, r = post(srv, date=d, start=start, end=end)
    assert st == 400
    assert r["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv, d) == []


def test_r2_boundaries_allowed(srv):
    d = fresh_date()
    assert post(srv, date=d, start="09:00", end="09:30")[0] == 201
    assert post(srv, date=d, start="17:30", end="18:00")[0] == 201


def test_r3_overlap_409(srv):
    # 시드: A 10:00~11:00 (김민수)
    before = listing(srv, DATE)
    st, r = post(srv, start="10:30", end="11:30")
    assert st == 409
    assert r["detail"] == "이미 예약된 시간입니다"
    assert listing(srv, DATE) == before


@pytest.mark.parametrize("start,end", [("10:00", "11:00"), ("09:30", "10:30"), ("10:30", "11:30"), ("10:00", "10:30"), ("09:30", "11:30")])
def test_r3_all_overlap_shapes_409(srv, start, end):
    # 같은 칸 · 앞쪽 걸침 · 뒤쪽 걸침 · 안에 포함 · 감싸기
    st, r = post(srv, start=start, end=end)
    assert st == 409
    assert r["detail"] == "이미 예약된 시간입니다"


def test_r3_adjacent_reservations_allowed(srv):
    d = fresh_date()
    assert post(srv, date=d, start="10:00", end="10:30")[0] == 201
    assert post(srv, date=d, start="10:30", end="11:00")[0] == 201  # 끝 = 시작
    assert post(srv, date=d, start="09:30", end="10:00")[0] == 201  # 앞에 붙임
    assert len(listing(srv, d)) == 3


def test_r3_adjacent_to_seed_allowed(srv):
    # 시드 A 10:00~11:00 바로 뒤 · 앞
    d = DATE
    st, r = post(srv, date=d, room="A", start="11:00", end="11:30", user="정하늘")
    assert st == 201
    st2, r2 = post(srv, date=d, room="A", start="09:30", end="10:00", user="정하늘")
    assert st2 == 201
    delete(srv, r["res_id"], "정하늘")
    delete(srv, r2["res_id"], "정하늘")


def test_r4_over_2h_400(srv):
    d = fresh_date()
    st, r = post(srv, date=d, start="09:00", end="11:30")
    assert st == 400
    assert r["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert listing(srv, d) == []


def test_r4_exactly_2h_allowed(srv):
    d = fresh_date()
    assert post(srv, date=d, start="09:00", end="11:00")[0] == 201


def test_r4_just_over_2h_400(srv):
    d = fresh_date()
    assert post(srv, date=d, start="09:00", end="11:30")[0] == 400
    assert post(srv, date=d, start="13:00", end="15:30")[0] == 400


def test_r7_other_room_same_time_allowed(srv):
    d = fresh_date()
    assert post(srv, date=d, room="A", start="10:00", end="11:00")[0] == 201
    assert post(srv, date=d, room="B", start="10:00", end="11:00")[0] == 201
    assert post(srv, date=d, room="C", start="10:00", end="11:00")[0] == 201
    assert post(srv, date=d, room="A", start="10:00", end="11:00")[0] == 409


def test_overlap_only_within_same_date(srv):
    d = fresh_date()
    assert post(srv, date=d, start="10:00", end="11:00")[0] == 201  # 시드 A 10:00 은 DATE 에만 있음
    assert post(srv, date="2030-02-02", start="10:00", end="11:00")[0] == 201


def test_empty_value_400(srv):
    d = fresh_date()
    st, _ = post(srv, date=d, user="")
    assert st == 400
    st, _ = post(srv, date=d, start="")
    assert st == 400
    assert listing(srv, d) == []


# ---------------------------------------------------------------- 취소

def test_r5_delete_others_403(srv):
    d = fresh_date()
    _, r = post(srv, date=d, user="김민수")
    st, resp = delete(srv, r["res_id"], "박지연")
    assert st == 403
    assert resp["detail"] == "본인 예약만 취소할 수 있습니다"
    assert [x["res_id"] for x in listing(srv, d)] == [r["res_id"]]


def test_r5_delete_without_user_rejected(srv):
    d = fresh_date()
    _, r = post(srv, date=d, user="김민수")
    st, _ = http("DELETE", "%s/api/reservations/%d" % (srv.base, r["res_id"]))
    assert st in (400, 403, 422)
    assert len(listing(srv, d)) == 1


def test_delete_own_204_and_gone(srv):
    d = fresh_date()
    _, r = post(srv, date=d, user="김민수")
    st, resp = delete(srv, r["res_id"], "김민수")
    assert st == 204
    assert not resp
    assert listing(srv, d) == []


def test_delete_frees_the_time(srv):
    d = fresh_date()
    _, r = post(srv, date=d, user="김민수")
    assert post(srv, date=d, user="박지연")[0] == 409
    delete(srv, r["res_id"], "김민수")
    assert post(srv, date=d, user="박지연")[0] == 201


def test_delete_missing_404(srv):
    st, _ = delete(srv, 99999, "김민수")
    assert st == 404


# ---------------------------------------------------------------- 화면

URL_Q = "/?date="


def open_page(pw, srv, date=DATE, user=None):
    page = pw.new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto(srv.base + URL_Q + date)
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', user)
        page.wait_for_timeout(300)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_page_opens_with_title(srv):
    st, html = http("GET", srv.base + "/")
    assert st == 200
    assert "회의실" in html
    assert "다온소프트 회의실 예약" in html


def test_grid_has_54_slots(pw, srv):
    page = open_page(pw, srv)
    assert page.locator('[data-testid="slot"]').count() == 54
    page.close()


def test_grid_rooms_and_times(pw, srv):
    page = open_page(pw, srv)
    els = page.locator('[data-testid="slot"]')
    pairs = [(els.nth(i).get_attribute("data-room"), els.nth(i).get_attribute("data-start")) for i in range(els.count())]
    times = ["%02d:%02d" % (m // 60, m % 60) for m in range(9 * 60, 18 * 60, 30)]
    assert sorted(pairs) == sorted((r[0], t) for r in ROOMS for t in times)
    assert slot(page, "C", "17:30").count() == 1
    page.close()


def test_user_select_options(pw, srv):
    page = open_page(pw, srv)
    opts = page.locator('[data-testid="user-select"] option').all_text_contents()
    assert [o.strip() for o in opts if o.strip()] == USERS
    page.close()


def test_date_shown_and_query_param(pw, srv):
    page = open_page(pw, srv)
    assert DATE in page.locator('[data-testid="date"]').inner_text()
    page.close()
    d = fresh_date()
    page = open_page(pw, srv, date=d)
    assert d in page.locator('[data-testid="date"]').inner_text()
    states = {page.locator('[data-testid="slot"]').nth(i).get_attribute("data-state") for i in range(54)}
    assert states == {"free"}
    page.close()


def test_booked_slots_from_seed(pw, srv):
    page = open_page(pw, srv, user="정하늘")  # 시드에 예약이 없는 사용자
    for room, start in [("A", "10:00"), ("A", "10:30"), ("A", "14:00"), ("B", "10:00"), ("C", "16:00"), ("C", "17:30"), ("B", "13:00"), ("B", "14:30")]:
        assert slot(page, room, start).get_attribute("data-state") == "booked", (room, start)
    for room, start in [("A", "09:00"), ("A", "11:00"), ("A", "14:30"), ("B", "10:30"), ("C", "15:30")]:
        assert slot(page, room, start).get_attribute("data-state") == "free", (room, start)
    mine = page.locator('[data-testid="slot"][data-state="mine"]').count()
    assert mine == 0
    page.close()


def test_booked_slot_shows_user_name(pw, srv):
    page = open_page(pw, srv, user="정하늘")
    assert "김민수" in slot(page, "A", "10:00").inner_text()
    assert "박지연" in slot(page, "A", "14:00").inner_text()
    page.close()


def test_mine_state_for_selected_user(pw, srv):
    page = open_page(pw, srv, user="김민수")
    for room, start in [("A", "10:00"), ("A", "10:30"), ("B", "13:00"), ("B", "14:30")]:
        assert slot(page, room, start).get_attribute("data-state") == "mine", (room, start)
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    assert slot(page, "B", "10:00").get_attribute("data-state") == "booked"
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 6
    page.close()


def test_switching_user_changes_mine(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    page.select_option('[data-testid="user-select"]', "박지연")
    page.wait_for_timeout(300)
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.close()


def test_cancel_button_only_on_mine(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "B", "13:00").locator('[data-testid="cancel-btn"]').count() >= 1
    for room, start in [("A", "14:00"), ("B", "10:00"), ("C", "16:00")]:
        assert slot(page, room, start).locator('[data-testid="cancel-btn"]').count() == 0, (room, start)
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_no_cancel_button_when_other_user_selected(pw, srv):
    page = open_page(pw, srv, user="정하늘")
    assert page.locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_cancel_via_ui_removes_reservation(pw, srv):
    d = fresh_date()
    _, r = post(srv, date=d, room="C", start="11:00", end="11:30", user="한도윤")
    page = open_page(pw, srv, date=d, user="한도윤")
    s = slot(page, "C", "11:00")
    assert s.get_attribute("data-state") == "mine"
    s.locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_timeout(500)
    assert slot(page, "C", "11:00").get_attribute("data-state") == "free"
    assert listing(srv, d) == []
    page.close()


def test_reservation_made_via_api_appears_in_ui(pw, srv):
    d = fresh_date()
    post(srv, date=d, room="B", start="09:00", end="10:00", user="이서준")
    page = open_page(pw, srv, date=d, user="이서준")
    assert slot(page, "B", "09:00").get_attribute("data-state") == "mine"
    assert slot(page, "B", "09:30").get_attribute("data-state") == "mine"
    assert slot(page, "B", "10:00").get_attribute("data-state") == "free"
    page.close()


def test_message_line_exists(pw, srv):
    page = open_page(pw, srv)
    assert page.locator('[data-testid="message"]').count() == 1
    page.close()


def test_error_state_when_api_fails(pw, srv):
    page = pw.new_page()
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/?date=" + DATE)
    page.wait_for_timeout(1000)
    assert "불러오지 못했습니다" in page.content()
    page.close()
