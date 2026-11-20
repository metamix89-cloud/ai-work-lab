# -*- coding: utf-8 -*-
"""다온소프트 회의실 예약 — PRD 기준 테스트 (API 규칙 R1~R7 + 화면 F1·F6·R5·R6).

서버는 모듈 안에서 하나를 같이 쓰므로, 상태를 바꾸는 테스트는 테스트마다 새 날짜를 받아 서로 영향이 없게 한다.
"""
import itertools

import pytest

from conftest import DATE, RES, ROOMS, USERS, http

_days = itertools.count(1)


@pytest.fixture
def day():
    """이 테스트만 쓰는 빈 날짜 (고정 데이터에는 이 날짜의 예약이 없다)."""
    return "2027-03-%02d" % next(_days)


def body(date, start, end, room="A", user="박지연"):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def count(srv, date):
    status, data = http("GET", srv.base + "/api/reservations?date=" + date)
    assert status == 200
    return len(data)


# ---------------------------------------------------------------- 조회 API (F5)

def test_rooms_api(srv):
    status, data = http("GET", srv.base + "/api/rooms")
    assert status == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_reservations_api_returns_seed_for_date(srv):
    status, data = http("GET", srv.base + "/api/reservations?date=" + DATE)
    assert status == 200
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_reservations_api_filters_by_date(srv, day):
    status, data = http("GET", srv.base + "/api/reservations?date=" + day)
    assert status == 200 and data == []


# ---------------------------------------------------------------- 예약 생성 (F2)

def test_create_returns_201_and_reservation(srv, day):
    status, data = http("POST", srv.base + "/api/reservations", body(day, "13:00", "14:00"))
    assert status == 201
    assert data["room_id"] == "A" and data["date"] == day
    assert data["start"] == "13:00" and data["end"] == "14:00" and data["user"] == "박지연"
    assert isinstance(data["res_id"], int)
    _, listed = http("GET", srv.base + "/api/reservations?date=" + day)
    assert [r["res_id"] for r in listed] == [data["res_id"]]


def test_create_assigns_distinct_ids(srv, day):
    _, a = http("POST", srv.base + "/api/reservations", body(day, "09:00", "09:30"))
    _, b = http("POST", srv.base + "/api/reservations", body(day, "10:00", "10:30"))
    assert a["res_id"] != b["res_id"]


@pytest.mark.parametrize("field", ["room_id", "date", "start", "end", "user"])
def test_create_rejects_empty_value(srv, day, field):
    b = body(day, "13:00", "14:00")
    b[field] = ""
    status, data = http("POST", srv.base + "/api/reservations", b)
    assert status in (400, 422)
    assert count(srv, day) == 0


def test_create_rejects_empty_user_with_400(srv, day):
    status, data = http("POST", srv.base + "/api/reservations", body(day, "13:00", "14:00", user=""))
    assert status == 400
    assert data["detail"]


# ---------------------------------------------------------------- R1 30분 단위

@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("10:10", "10:50"), ("10:01", "11:00")])
def test_r1_non_30_minute_unit_is_400(srv, day, start, end):
    status, data = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 400
    assert data["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert count(srv, day) == 0


@pytest.mark.parametrize("start,end", [("10:00", "10:30"), ("10:30", "11:00")])
def test_r1_00_and_30_are_accepted(srv, day, start, end):
    status, _ = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 201


# ---------------------------------------------------------------- R2 09:00~18:00

@pytest.mark.parametrize("start,end", [("08:30", "09:30"), ("08:00", "09:00"), ("17:30", "18:30"), ("18:00", "18:30"), ("19:00", "19:30")])
def test_r2_outside_hours_is_400(srv, day, start, end):
    status, data = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 400
    assert data["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert count(srv, day) == 0


@pytest.mark.parametrize("start,end", [("11:00", "10:00"), ("11:00", "11:00")])
def test_r2_end_must_be_after_start(srv, day, start, end):
    status, data = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 400
    assert data["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert count(srv, day) == 0


@pytest.mark.parametrize("start,end", [("09:00", "09:30"), ("17:30", "18:00")])
def test_r2_boundary_slots_are_accepted(srv, day, start, end):
    status, _ = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 201


# ---------------------------------------------------------------- R3 겹침

@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 똑같은 시간
    ("10:30", "11:30"),   # 뒤쪽이 겹침
    ("09:30", "10:30"),   # 앞쪽이 겹침
    ("10:30", "11:00"),   # 기존 안에 쏙 들어감
    ("09:00", "12:00"),   # 기존을 감쌈
])
def test_r3_overlap_is_409_and_count_unchanged(srv, day, start, end):
    http("POST", srv.base + "/api/reservations", body(day, "10:00", "11:00", user="김민수"))
    status, data = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 409
    assert data["detail"] == "이미 예약된 시간입니다"
    assert count(srv, day) == 1


@pytest.mark.parametrize("start,end", [("09:30", "10:00"), ("11:00", "11:30")])
def test_r3_back_to_back_is_allowed(srv, day, start, end):
    http("POST", srv.base + "/api/reservations", body(day, "10:00", "11:00", user="김민수"))
    status, _ = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 201
    assert count(srv, day) == 2


def test_r3_adjacent_on_both_sides_of_a_30_minute_booking(srv, day):
    assert http("POST", srv.base + "/api/reservations", body(day, "10:00", "10:30"))[0] == 201
    assert http("POST", srv.base + "/api/reservations", body(day, "10:30", "11:00"))[0] == 201
    assert count(srv, day) == 2


def test_r3_same_time_on_another_date_is_allowed(srv, day):
    other = "2027-04-%02d" % next(_days)
    http("POST", srv.base + "/api/reservations", body(day, "10:00", "11:00"))
    assert http("POST", srv.base + "/api/reservations", body(other, "10:00", "11:00"))[0] == 201


def test_r3_rejects_overlap_with_seed_reservation(srv):
    before = count(srv, DATE)
    status, _ = http("POST", srv.base + "/api/reservations", body(DATE, "10:30", "11:30", room="A"))
    assert status == 409
    assert count(srv, DATE) == before


# ---------------------------------------------------------------- R4 최대 2시간

@pytest.mark.parametrize("start,end", [("09:00", "11:30"), ("09:00", "12:00"), ("13:00", "16:00")])
def test_r4_over_two_hours_is_400(srv, day, start, end):
    status, data = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 400
    assert data["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert count(srv, day) == 0


@pytest.mark.parametrize("start,end", [("09:00", "11:00"), ("16:00", "18:00")])
def test_r4_exactly_two_hours_is_201(srv, day, start, end):
    status, _ = http("POST", srv.base + "/api/reservations", body(day, start, end))
    assert status == 201


# ---------------------------------------------------------------- R7 회의실 독립

def test_r7_other_rooms_are_independent(srv, day):
    assert http("POST", srv.base + "/api/reservations", body(day, "10:00", "11:00", room="A"))[0] == 201
    assert http("POST", srv.base + "/api/reservations", body(day, "10:00", "11:00", room="B"))[0] == 201
    assert http("POST", srv.base + "/api/reservations", body(day, "10:00", "11:00", room="C"))[0] == 201
    assert count(srv, day) == 3


# ---------------------------------------------------------------- R5 취소는 본인만 (F3)

def _make(srv, day, user="김민수"):
    _, r = http("POST", srv.base + "/api/reservations", body(day, "10:00", "11:00", user=user))
    return r["res_id"]


def test_r5_delete_by_other_user_is_403_and_stays(srv, day):
    rid = _make(srv, day, "김민수")
    status, data = http("DELETE", srv.base + "/api/reservations/%d?user=박지연" % rid)
    assert status == 403
    assert data["detail"] == "본인 예약만 취소할 수 있습니다"
    assert count(srv, day) == 1


def test_r5_delete_without_user_is_403_and_stays(srv, day):
    rid = _make(srv, day, "김민수")
    status, _ = http("DELETE", srv.base + "/api/reservations/%d" % rid)
    assert status == 403
    assert count(srv, day) == 1


def test_r5_delete_by_owner_is_204_and_gone(srv, day):
    rid = _make(srv, day, "김민수")
    status, _ = http("DELETE", srv.base + "/api/reservations/%d?user=김민수" % rid)
    assert status == 204
    assert count(srv, day) == 0


def test_delete_frees_the_slot_for_rebooking(srv, day):
    rid = _make(srv, day, "김민수")
    http("DELETE", srv.base + "/api/reservations/%d?user=김민수" % rid)
    assert http("POST", srv.base + "/api/reservations", body(day, "10:00", "11:00"))[0] == 201


def test_delete_unknown_id_is_404(srv):
    status, _ = http("DELETE", srv.base + "/api/reservations/999999?user=김민수")
    assert status == 404


# ---------------------------------------------------------------- 화면 (F1·F4·F6, R5·R6)

def _open(pw, srv, date=DATE, user=None):
    page = pw.new_page()
    page.goto(srv.base + "/?date=" + date)
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', user)
    return page


def _slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_ui_page_opens_with_title(pw, srv):
    page = pw.new_page()
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("h1")
    page.close()


def test_ui_has_54_slots(pw, srv):
    page = _open(pw, srv)
    assert page.locator('[data-testid="slot"]').count() == 54
    page.close()


def test_ui_slots_per_room_and_times(pw, srv):
    page = _open(pw, srv)
    for room, _, _ in ROOMS:
        assert page.locator('[data-testid="slot"][data-room="%s"]' % room).count() == 18
    assert _slot(page, "A", "09:00").count() == 1
    assert _slot(page, "A", "17:30").count() == 1
    assert _slot(page, "A", "18:00").count() == 0
    page.close()


def test_ui_slot_states_are_only_the_three(pw, srv):
    page = _open(pw, srv)
    states = set(page.locator('[data-testid="slot"]').evaluate_all("els => els.map(e => e.dataset.state)"))
    assert states <= {"free", "booked", "mine"}
    page.close()


def test_ui_date_and_user_select_options(pw, srv):
    page = _open(pw, srv)
    assert DATE in page.inner_text('[data-testid="date"]')
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts] == USERS
    page.close()


def test_ui_message_line_exists(pw, srv):
    page = _open(pw, srv)
    assert page.locator('[data-testid="message"]').count() == 1
    page.close()


def test_ui_seed_reservations_show_as_booked(pw, srv):
    page = _open(pw, srv, user="박지연")
    for room, start in [("A", "10:00"), ("A", "10:30"), ("B", "10:00"), ("C", "16:00"), ("C", "17:30"), ("B", "14:30")]:
        assert _slot(page, room, start).get_attribute("data-state") == "booked", (room, start)
    page.close()


def test_ui_free_slots(pw, srv):
    page = _open(pw, srv, user="박지연")
    for room, start in [("A", "09:00"), ("A", "11:00"), ("A", "14:30"), ("B", "10:30"), ("B", "15:00"), ("C", "15:30")]:
        assert _slot(page, room, start).get_attribute("data-state") == "free", (room, start)
    page.close()


def test_ui_booked_slot_shows_user_name(pw, srv):
    page = _open(pw, srv, user="박지연")
    assert "김민수" in _slot(page, "A", "10:00").inner_text()
    assert "이서준" in _slot(page, "B", "10:00").inner_text()
    page.close()


def test_ui_own_reservations_are_mine(pw, srv):
    page = _open(pw, srv, user="김민수")
    for room, start in [("A", "10:00"), ("A", "10:30"), ("B", "13:00"), ("B", "14:30")]:
        assert _slot(page, room, start).get_attribute("data-state") == "mine", (room, start)
    assert "김민수" in _slot(page, "A", "10:00").inner_text()
    # 남의 예약은 그대로 booked
    assert _slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.close()


def test_ui_r6_changing_user_changes_mine(pw, srv):
    page = _open(pw, srv, user="김민수")
    assert _slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert _slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.select_option('[data-testid="user-select"]', "박지연")
    assert _slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert _slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.close()


def test_ui_no_mine_when_user_has_no_reservation(pw, srv):
    page = _open(pw, srv, user="한도윤")
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 0
    assert page.locator('[data-testid="slot"][data-state="booked"]').count() == 12  # 시드 5건 = 2+1+1+4+4칸
    page.close()


def test_ui_r5_cancel_button_only_on_mine(pw, srv):
    page = _open(pw, srv, user="김민수")
    assert _slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert _slot(page, "B", "13:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert _slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() == 0   # 박지연
    assert _slot(page, "B", "10:00").locator('[data-testid="cancel-btn"]').count() == 0   # 이서준
    assert _slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0   # 빈 칸
    page.close()


def test_ui_other_users_see_no_cancel_on_kim_reservation(pw, srv):
    page = _open(pw, srv, user="박지연")
    assert _slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_ui_f4_other_date_is_empty(pw, srv, day):
    page = _open(pw, srv, date=day, user="김민수")
    assert page.locator('[data-testid="slot"]').count() == 54
    assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54
    assert day in page.inner_text('[data-testid="date"]')
    page.close()


def test_ui_reflects_api_reservation(pw, srv, day):
    http("POST", srv.base + "/api/reservations", body(day, "09:00", "10:00", room="C", user="정하늘"))
    page = _open(pw, srv, date=day, user="정하늘")
    assert _slot(page, "C", "09:00").get_attribute("data-state") == "mine"
    assert _slot(page, "C", "09:30").get_attribute("data-state") == "mine"
    assert _slot(page, "C", "10:00").get_attribute("data-state") == "free"
    page.close()


def test_ui_cancel_button_removes_own_reservation(pw, srv, day):
    _, r = http("POST", srv.base + "/api/reservations", body(day, "11:00", "11:30", room="B", user="최유나"))
    page = _open(pw, srv, date=day, user="최유나")
    page.once("dialog", lambda d: d.accept())   # 확인창이 뜨는 구현도 허용
    _slot(page, "B", "11:00").locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=B][data-start=\"11:00\"]').dataset.state === 'free'")
    assert count(srv, day) == 0
    page.close()
