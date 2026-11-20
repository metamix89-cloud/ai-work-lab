# -*- coding: utf-8 -*-
"""PRD.md 기준 회의실 예약 앱 테스트.

srv 는 모듈 단위라 서버가 테스트 사이에 유지된다. 그래서 쓰기 테스트는 고정 데이터 날짜(DATE)를 건드리지 않고
테스트마다 따로 쓰는 날짜에서 예약한다(서로 영향 없음). 고정 데이터를 읽기만 하는 테스트만 DATE 를 쓴다.
"""
import pytest

from conftest import DATE, ROOMS, USERS, RES, http

URL = "/api/reservations"


def body(room="A", date="2030-01-01", start="09:00", end="10:00", user="김민수"):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def post(srv, **kw):
    return http("POST", srv.base + URL, body(**kw))


def listing(srv, date):
    st, data = http("GET", srv.base + URL + "?date=" + date)
    assert st == 200
    return data


# ---------------------------------------------------------------- 조회 API

def test_rooms_api(srv):
    st, data = http("GET", srv.base + "/api/rooms")
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_list_reservations_of_seed_date(srv):
    data = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_list_reservations_filters_by_date(srv):
    assert listing(srv, "2030-02-02") == []
    assert all(r["date"] == DATE for r in listing(srv, DATE))


# ---------------------------------------------------------------- 예약 생성

def test_create_returns_201_and_reservation(srv):
    st, data = post(srv, date="2030-03-01", room="C", start="13:00", end="14:00", user="박지연")
    assert st == 201
    assert data["room_id"] == "C" and data["date"] == "2030-03-01"
    assert data["start"] == "13:00" and data["end"] == "14:00" and data["user"] == "박지연"
    assert data["res_id"]
    assert [r["res_id"] for r in listing(srv, "2030-03-01")] == [data["res_id"]]


def test_create_ids_are_unique(srv):
    _, a = post(srv, date="2030-03-02", start="09:00", end="09:30")
    _, b = post(srv, date="2030-03-02", start="09:30", end="10:00")
    assert a["res_id"] != b["res_id"]


# ---------------------------------------------------------------- R3 겹침

@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),  # 완전히 같음
    ("10:30", "11:30"),  # 뒤쪽 겹침
    ("09:30", "10:30"),  # 앞쪽 겹침
    ("10:00", "10:30"),  # 기존 안에 포함
    ("09:30", "11:30"),  # 기존을 감쌈
])
def test_overlap_is_409_and_count_unchanged(srv, start, end):
    before = listing(srv, DATE)
    st, data = post(srv, date=DATE, room="A", start=start, end=end, user="한도윤")
    assert st == 409
    assert data["detail"] == "이미 예약된 시간입니다"
    assert listing(srv, DATE) == before


def test_back_to_back_after_is_allowed(srv):
    d = "2030-04-01"
    assert post(srv, date=d, start="10:00", end="10:30")[0] == 201
    assert post(srv, date=d, start="10:30", end="11:00")[0] == 201


def test_back_to_back_before_is_allowed(srv):
    d = "2030-04-02"
    assert post(srv, date=d, start="10:30", end="11:00")[0] == 201
    assert post(srv, date=d, start="10:00", end="10:30")[0] == 201


def test_back_to_back_against_seed_reservation(srv):
    # 시드: A 10:00~11:00 (김민수). 11:00 시작 / 10:00 끝은 붙여 예약.
    # 시드 날짜를 건드리지 않도록 같은 모양을 다른 날짜에서 만든다.
    d = "2030-04-03"
    assert post(srv, date=d, start="10:00", end="11:00")[0] == 201
    assert post(srv, date=d, start="11:00", end="12:00", user="박지연")[0] == 201
    assert post(srv, date=d, start="09:00", end="10:00", user="박지연")[0] == 201


def test_same_time_other_room_is_independent(srv):
    d = "2030-04-04"
    assert post(srv, date=d, room="A", start="10:00", end="11:00")[0] == 201
    assert post(srv, date=d, room="B", start="10:00", end="11:00")[0] == 201
    assert post(srv, date=d, room="A", start="10:00", end="11:00")[0] == 409


def test_same_time_other_date_is_independent(srv):
    assert post(srv, date="2030-04-05", start="10:00", end="11:00")[0] == 201
    assert post(srv, date="2030-04-06", start="10:00", end="11:00")[0] == 201


# ---------------------------------------------------------------- R1 30분 단위

@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("10:10", "10:50")])
def test_non_30min_unit_is_400(srv, start, end):
    st, data = post(srv, date="2030-05-01", start=start, end=end)
    assert st == 400
    assert data["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv, "2030-05-01") == []


# ---------------------------------------------------------------- R2 시간대

@pytest.mark.parametrize("start,end", [
    ("17:30", "18:30"),  # 끝이 18:00 넘음
    ("08:30", "09:30"),  # 시작이 09:00 전
    ("08:00", "09:00"),  # 통째로 앞
    ("18:00", "18:30"),  # 통째로 뒤
])
def test_outside_hours_is_400(srv, start, end):
    st, data = post(srv, date="2030-05-02", start=start, end=end)
    assert st == 400
    assert data["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv, "2030-05-02") == []


@pytest.mark.parametrize("start,end", [("11:00", "11:00"), ("12:00", "11:00")])
def test_end_not_after_start_is_400(srv, start, end):
    st, _ = post(srv, date="2030-05-03", start=start, end=end)
    assert st == 400
    assert listing(srv, "2030-05-03") == []


def test_hours_boundaries_are_allowed(srv):
    d = "2030-05-04"
    assert post(srv, date=d, start="09:00", end="09:30")[0] == 201
    assert post(srv, date=d, start="17:30", end="18:00")[0] == 201


# ---------------------------------------------------------------- R4 최대 2시간

def test_over_2h_is_400(srv):
    st, data = post(srv, date="2030-06-01", start="09:00", end="11:30")
    assert st == 400
    assert data["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert listing(srv, "2030-06-01") == []


def test_just_over_2h_is_400(srv):
    assert post(srv, date="2030-06-02", start="09:00", end="11:30")[0] == 400
    assert post(srv, date="2030-06-02", start="13:00", end="15:30")[0] == 400


def test_exactly_2h_is_201(srv):
    assert post(srv, date="2030-06-03", start="09:00", end="11:00")[0] == 201


def test_1h30_is_201(srv):
    assert post(srv, date="2030-06-04", start="14:00", end="15:30")[0] == 201


# ---------------------------------------------------------------- 빈 값

@pytest.mark.parametrize("field", ["room_id", "date", "start", "end", "user"])
def test_empty_field_is_rejected(srv, field):
    b = body(date="2030-07-01")
    b[field] = ""
    st, _ = http("POST", srv.base + URL, b)
    assert st in (400, 422)
    assert listing(srv, "2030-07-01") == []


def test_missing_field_is_rejected(srv):
    b = body(date="2030-07-02")
    del b["user"]
    st, _ = http("POST", srv.base + URL, b)
    assert st in (400, 422)
    assert listing(srv, "2030-07-02") == []


# ---------------------------------------------------------------- R5 취소

def test_cancel_by_other_is_403_and_stays(srv):
    _, r = post(srv, date="2030-08-01", user="김민수")
    st, data = http("DELETE", "%s%s/%d?user=%s" % (srv.base, URL, r["res_id"], "박지연"))
    assert st == 403
    assert data["detail"] == "본인 예약만 취소할 수 있습니다"
    assert [x["res_id"] for x in listing(srv, "2030-08-01")] == [r["res_id"]]


def test_cancel_without_user_is_not_allowed(srv):
    _, r = post(srv, date="2030-08-02", user="김민수")
    st, _ = http("DELETE", "%s%s/%d" % (srv.base, URL, r["res_id"]))
    assert st in (400, 403, 422)
    assert len(listing(srv, "2030-08-02")) == 1


def test_cancel_by_owner_is_204_and_gone(srv):
    _, r = post(srv, date="2030-08-03", user="김민수")
    st, _ = http("DELETE", "%s%s/%d?user=%s" % (srv.base, URL, r["res_id"], "김민수"))
    assert st == 204
    assert listing(srv, "2030-08-03") == []


def test_cancel_frees_the_time(srv):
    d = "2030-08-04"
    _, r = post(srv, date=d, start="10:00", end="11:00")
    assert post(srv, date=d, start="10:00", end="11:00", user="박지연")[0] == 409
    assert http("DELETE", "%s%s/%d?user=김민수" % (srv.base, URL, r["res_id"]))[0] == 204
    assert post(srv, date=d, start="10:00", end="11:00", user="박지연")[0] == 201


def test_cancel_unknown_id_is_404(srv):
    st, _ = http("DELETE", "%s%s/%d?user=김민수" % (srv.base, URL, 999999))
    assert st == 404


# ---------------------------------------------------------------- 화면 (T1~T3, T9, R6)

def open_page(pw, srv, date=DATE, user=None):
    page = pw.new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto("%s/?date=%s" % (srv.base, date))
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', user)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_page_opens_with_title(pw, srv):
    page = pw.new_page()
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("body")
    page.close()


def test_grid_has_54_slots(pw, srv):
    page = open_page(pw, srv)
    assert page.locator('[data-testid="slot"]').count() == 54
    for room, _, _ in ROOMS:
        assert page.locator('[data-testid="slot"][data-room="%s"]' % room).count() == 18
    starts = page.locator('[data-testid="slot"][data-room="A"]').evaluate_all("els => els.map(e => e.dataset.start)")
    assert starts[0] == "09:00" and starts[-1] == "17:30" and len(set(starts)) == 18
    page.close()


def test_date_is_shown(pw, srv):
    page = open_page(pw, srv)
    assert DATE in page.inner_text('[data-testid="date"]')
    page.close()


def test_user_select_options_are_users(pw, srv):
    page = open_page(pw, srv)
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts if o.strip()] == USERS
    page.close()


def test_slot_states_for_seed(pw, srv):
    page = open_page(pw, srv, user="박지연")
    # 김민수 A 10:00~11:00 → 박지연 입장에서는 남의 예약
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "10:30").get_attribute("data-state") == "booked"
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"
    assert slot(page, "A", "09:30").get_attribute("data-state") == "free"
    # 박지연 A 14:00~14:30 → 내 예약, 14:30 은 빈 칸
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "14:30").get_attribute("data-state") == "free"
    page.close()


def test_booked_slot_shows_user_name(pw, srv):
    page = open_page(pw, srv, user="박지연")
    assert "김민수" in slot(page, "A", "10:00").inner_text()
    assert "이서준" in slot(page, "B", "10:00").inner_text()
    page.close()


def test_multi_hour_reservation_fills_all_slots(pw, srv):
    page = open_page(pw, srv, user="김민수")
    # 최유나 C 16:00~18:00 → 4칸, 김민수 B 13:00~15:00 → 4칸
    for t in ("16:00", "16:30", "17:00", "17:30"):
        assert slot(page, "C", t).get_attribute("data-state") == "booked"
    for t in ("13:00", "13:30", "14:00", "14:30"):
        assert slot(page, "B", t).get_attribute("data-state") == "mine"
    assert slot(page, "B", "15:00").get_attribute("data-state") == "free"
    page.close()


def test_mine_follows_selected_user(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:30").get_attribute("data-state") == "mine"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.select_option('[data-testid="user-select"]', "박지연")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.select_option('[data-testid="user-select"]', "한도윤")
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 0
    page.close()


def test_all_free_when_other_date(pw, srv):
    page = open_page(pw, srv, date="2030-09-09", user="김민수")
    assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54
    page.close()


def test_cancel_button_only_on_mine(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() == 0  # 남의 예약
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0  # 빈 칸
    # 취소 버튼은 mine 칸에만 있다
    n_bad = page.locator('[data-testid="slot"]:not([data-state="mine"]) [data-testid="cancel-btn"]').count()
    assert n_bad == 0
    page.close()


def test_no_cancel_button_for_user_without_reservations(pw, srv):
    page = open_page(pw, srv, user="한도윤")
    assert page.locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_cancel_from_screen_removes_reservation(pw, srv):
    d = "2030-09-10"
    _, r = post(srv, date=d, room="B", start="11:00", end="11:30", user="정하늘")
    page = open_page(pw, srv, date=d, user="정하늘")
    s = slot(page, "B", "11:00")
    assert s.get_attribute("data-state") == "mine"
    s.locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"slot\"][data-room=\"B\"][data-start=\"11:00\"]').dataset.state === 'free'")
    assert listing(srv, d) == []
    page.close()
