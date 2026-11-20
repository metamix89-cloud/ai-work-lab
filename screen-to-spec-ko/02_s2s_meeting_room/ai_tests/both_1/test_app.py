# -*- coding: utf-8 -*-
"""다온소프트 회의실 예약 — PRD.md 기준 테스트.

srv 는 모듈 단위로 한 번만 뜨므로 테스트끼리 상태를 공유한다.
그래서 예약을 만드는 테스트는 고정 데이터(DATE)가 아닌 자기 전용 날짜를 쓴다(순서 무관).
"""
import pytest

from conftest import DATE, ROOMS, USERS, RES, http

SLOT = '[data-testid="slot"]'
SELECT = '[data-testid="user-select"]'


def body(room="A", date=DATE, start="13:00", end="14:00", user="박지연"):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def listing(srv, date):
    status, data = http("GET", "%s/api/reservations?date=%s" % (srv.base, date))
    assert status == 200
    return data


def post(srv, **kw):
    return http("POST", srv.base + "/api/reservations", body(**kw))


# ───────────────────────── API: 조회 ─────────────────────────

def test_rooms_api(srv):
    status, data = http("GET", srv.base + "/api/rooms")
    assert status == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_reservations_api_returns_seed_for_date(srv):
    data = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_reservations_api_filters_by_date(srv):
    assert listing(srv, "2030-01-01") == []


# ───────────────────────── API: 생성 · 규칙 ─────────────────────────

def test_create_returns_201_and_reservation(srv):
    d = "2027-01-04"
    status, data = post(srv, date=d, start="13:00", end="14:00")
    assert status == 201
    assert (data["room_id"], data["date"], data["start"], data["end"], data["user"]) == ("A", d, "13:00", "14:00", "박지연")
    assert isinstance(data["res_id"], int)
    assert data["res_id"] not in [r[0] for r in RES]
    assert data["res_id"] in [r["res_id"] for r in listing(srv, d)]


def test_overlap_same_slot_is_409(srv):
    before = listing(srv, DATE)
    status, data = post(srv, date=DATE, start="10:00", end="11:00", user="박지연")
    assert status == 409
    assert data["detail"] == "이미 예약된 시간입니다"
    assert listing(srv, DATE) == before


@pytest.mark.parametrize("start,end", [
    ("09:30", "10:30"),   # 앞쪽이 걸침
    ("10:30", "11:30"),   # 뒤쪽이 걸침
    ("10:00", "10:30"),   # 안에 포함
    ("09:30", "11:30"),   # 바깥을 감쌈
])
def test_overlap_variants_are_409(srv, start, end):
    before = listing(srv, DATE)
    status, data = post(srv, date=DATE, start=start, end=end)
    assert status == 409
    assert data["detail"] == "이미 예약된 시간입니다"
    assert len(listing(srv, DATE)) == len(before)


def test_back_to_back_is_allowed(srv):
    """R3: 끝나는 시각 = 시작 시각은 겹침이 아니다. 새 예약이 기존 앞·뒤에 붙는다."""
    d = "2027-01-05"
    assert post(srv, date=d, start="10:00", end="10:30")[0] == 201
    assert post(srv, date=d, start="10:30", end="11:00")[0] == 201   # 뒤에 붙임
    assert post(srv, date=d, start="09:30", end="10:00")[0] == 201   # 앞에 붙임
    assert len(listing(srv, d)) == 3


def test_back_to_back_against_seed(srv):
    """고정 데이터 A 10:00~11:00 의 바로 뒤(11:00)와 바로 앞(09:30~10:00)."""
    d = DATE
    s1, _ = post(srv, room="A", date=d, start="11:00", end="11:30", user="이서준")
    s2, _ = post(srv, room="A", date=d, start="09:00", end="10:00", user="이서준")
    assert (s1, s2) == (201, 201)


def test_other_room_same_time_is_independent(srv):
    """R7: A 10:00 이 예약돼 있어도 C 10:00 은 가능."""
    status, _ = post(srv, room="C", date=DATE, start="10:00", end="11:00", user="한도윤")
    assert status == 201


def test_same_time_other_date_is_independent(srv):
    status, _ = post(srv, room="A", date="2027-01-06", start="10:00", end="11:00")
    assert status == 201


@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("10:10", "10:50")])
def test_not_30min_unit_is_400(srv, start, end):
    d = "2027-01-07"
    status, data = post(srv, date=d, start=start, end=end)
    assert status == 400
    assert data["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv, d) == []


@pytest.mark.parametrize("start,end", [
    ("08:30", "09:30"),   # 시작이 너무 이름
    ("17:30", "18:30"),   # 끝이 너무 늦음
    ("10:00", "10:00"),   # 길이 0
    ("11:00", "10:30"),   # 끝이 시작보다 앞
])
def test_outside_hours_or_bad_order_is_400(srv, start, end):
    d = "2027-01-08"
    status, data = post(srv, date=d, start=start, end=end)
    assert status == 400
    assert data["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv, d) == []


def test_boundaries_09_and_18_are_allowed(srv):
    d = "2027-01-09"
    assert post(srv, room="A", date=d, start="09:00", end="09:30")[0] == 201
    assert post(srv, room="A", date=d, start="17:30", end="18:00")[0] == 201


def test_over_2_hours_is_400(srv):
    d = "2027-01-11"
    status, data = post(srv, date=d, start="10:00", end="12:30")
    assert status == 400
    assert data["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert listing(srv, d) == []


def test_exactly_2_hours_is_201(srv):
    status, _ = post(srv, date="2027-01-13", start="10:00", end="12:00")
    assert status == 201


def test_empty_user_is_400(srv):
    d = "2027-01-14"
    status, data = post(srv, date=d, user="")
    assert status == 400
    assert listing(srv, d) == []


# ───────────────────────── API: 취소 ─────────────────────────

def test_delete_others_is_403_and_kept(srv):
    d = "2027-02-01"
    _, made = post(srv, date=d, user="김민수")
    url = "%s/api/reservations/%d?user=%s" % (srv.base, made["res_id"], "박지연")
    status, data = http("DELETE", url)
    assert status == 403
    assert data["detail"] == "본인 예약만 취소할 수 있습니다"
    assert made["res_id"] in [r["res_id"] for r in listing(srv, d)]


def test_delete_without_user_is_rejected(srv):
    d = "2027-02-02"
    _, made = post(srv, date=d, user="김민수")
    status, _ = http("DELETE", "%s/api/reservations/%d" % (srv.base, made["res_id"]))
    assert status == 403
    assert made["res_id"] in [r["res_id"] for r in listing(srv, d)]


def test_delete_own_is_204_and_gone(srv):
    d = "2027-02-03"
    _, made = post(srv, date=d, user="김민수")
    status, _ = http("DELETE", "%s/api/reservations/%d?user=%s" % (srv.base, made["res_id"], "김민수"))
    assert status == 204
    assert listing(srv, d) == []


def test_deleted_slot_can_be_booked_again(srv):
    d = "2027-02-04"
    _, made = post(srv, date=d, start="10:00", end="11:00", user="김민수")
    http("DELETE", "%s/api/reservations/%d?user=%s" % (srv.base, made["res_id"], "김민수"))
    assert post(srv, date=d, start="10:00", end="11:00", user="박지연")[0] == 201


def test_delete_missing_is_404(srv):
    status, _ = http("DELETE", "%s/api/reservations/99999?user=%s" % (srv.base, "김민수"))
    assert status == 404


# ───────────────────────── 화면 ─────────────────────────

def open_page(pw, srv, date=None, user=None):
    page = pw.new_page()
    page.set_default_timeout(5000)
    page.goto(srv.base + "/" + ("?date=" + date if date else ""))
    page.wait_for_selector(SLOT)
    if user:
        page.select_option(SELECT, user)
    return page


def slot(page, room, start):
    return page.locator('%s[data-room="%s"][data-start="%s"]' % (SLOT, room, start))


def test_page_opens_with_title(srv):
    status, text = http("GET", srv.base + "/")
    assert status == 200
    assert "회의실" in text


def test_grid_has_54_slots(pw, srv):
    page = open_page(pw, srv)
    assert page.locator(SLOT).count() == 54
    for room, _, _ in ROOMS:
        assert page.locator('%s[data-room="%s"]' % (SLOT, room)).count() == 18
    page.close()


def test_slot_times_run_0900_to_1730(pw, srv):
    page = open_page(pw, srv)
    starts = page.locator('%s[data-room="A"]' % SLOT).evaluate_all("els => els.map(e => e.dataset.start)")
    assert starts[0] == "09:00" and starts[-1] == "17:30" and len(starts) == 18
    assert starts == sorted(starts)
    page.close()


def test_header_shows_title_date_and_users(pw, srv):
    page = open_page(pw, srv)
    assert "다온소프트 회의실 예약" in page.inner_text("body")
    assert DATE in page.locator('[data-testid="date"]').inner_text()
    opts = page.locator(SELECT + " option").all_inner_texts()
    assert [o.strip() for o in opts] == USERS
    page.close()


def test_booked_slots_from_seed(pw, srv):
    page = open_page(pw, srv, user="박지연")
    for start in ("10:00", "10:30"):
        s = slot(page, "A", start)
        assert s.get_attribute("data-state") == "booked"
        assert "김민수" in s.inner_text()
    page.close()


def test_free_slots_are_free(pw, srv):
    page = open_page(pw, srv, user="박지연")
    for room, start in (("A", "09:00"), ("A", "11:00"), ("A", "14:30"), ("B", "10:30"), ("C", "15:30")):
        assert slot(page, room, start).get_attribute("data-state") == "free", (room, start)
    page.close()


def test_booking_end_is_exclusive_in_grid(pw, srv):
    """C 16:00~18:00 → 16:00~17:30 네 칸 모두 예약, 마지막 칸(17:30)도 예약."""
    page = open_page(pw, srv, user="김민수")
    for start in ("16:00", "16:30", "17:00", "17:30"):
        assert slot(page, "C", start).get_attribute("data-state") == "booked"
    page.close()


def test_mine_when_user_selected(pw, srv):
    page = open_page(pw, srv, user="김민수")
    for room, start in (("A", "10:00"), ("A", "10:30"), ("B", "13:00"), ("B", "14:30")):
        assert slot(page, room, start).get_attribute("data-state") == "mine", (room, start)
    # 남의 예약은 그대로 booked
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.close()


def test_changing_user_changes_mine(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.select_option(SELECT, "박지연")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=A][data-start=\"10:00\"]').dataset.state === 'booked'")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.close()


def test_cancel_button_only_on_mine(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() == 0   # 남의 booked
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0   # free
    # 화면 전체에서 취소 버튼은 mine 칸 안에만 있다
    mine = page.locator(SLOT + '[data-state="mine"]').count()
    assert mine > 0
    assert page.locator(SLOT + ':not([data-state="mine"]) [data-testid="cancel-btn"]').count() == 0
    page.close()


def test_no_cancel_button_for_user_without_reservations(pw, srv):
    page = open_page(pw, srv, user="한도윤")
    assert page.locator('[data-testid="cancel-btn"]').count() == 0
    assert page.locator(SLOT + '[data-state="mine"]').count() == 0
    page.close()


def test_date_query_shows_other_day_empty(pw, srv):
    page = open_page(pw, srv, date="2030-05-05", user="김민수")
    assert "2030-05-05" in page.locator('[data-testid="date"]').inner_text()
    assert page.locator(SLOT).count() == 54
    assert page.locator(SLOT + '[data-state="free"]').count() == 54
    page.close()


def test_ui_cancel_removes_own_reservation(pw, srv):
    d = "2027-03-01"
    _, made = post(srv, room="B", date=d, start="11:00", end="11:30", user="김민수")
    page = open_page(pw, srv, date=d, user="김민수")
    page.on("dialog", lambda dlg: dlg.accept())
    assert slot(page, "B", "11:00").get_attribute("data-state") == "mine"
    slot(page, "B", "11:00").locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=B][data-start=\"11:00\"]').dataset.state === 'free'")
    assert listing(srv, d) == []
    page.close()


def test_api_failure_shows_error_state(pw, srv):
    page = pw.new_page()
    page.set_default_timeout(5000)
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/")
    page.wait_for_selector("text=불러오지 못했습니다")
    page.close()
