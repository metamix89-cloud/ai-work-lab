# -*- coding: utf-8 -*-
"""다온소프트 회의실 예약 — PRD.md 기준 테스트.

srv 는 모듈 단위로 한 번만 뜨므로 테스트끼리 상태를 공유한다.
그래서 각 쓰기 테스트는 서로 겹치지 않는 (회의실, 시각) 칸만 쓰고, 개수는 '전후 비교'로 본다.
"""
import pytest

from conftest import DATE, RES, ROOMS, USERS, http

OTHER_DATE = "2026-11-04"
EMPTY_DATE = "2026-11-05"


def api(srv, path):
    return srv.base + path


def day(srv, date=DATE):
    st, body = http("GET", api(srv, "/api/reservations?date=" + date))
    assert st == 200
    return body


def post(srv, room, start, end, user="한도윤", date=DATE):
    return http("POST", api(srv, "/api/reservations"),
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


# ---------------------------------------------------------------- F5 조회
def test_rooms_api(srv):
    st, body = http("GET", api(srv, "/api/rooms"))
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in body] == ROOMS


def test_reservations_api_returns_seed_for_date(srv):
    got = {r["res_id"]: r for r in day(srv)}
    for res_id, room, date, start, end, user in RES:
        assert got[res_id] == {"res_id": res_id, "room_id": room, "date": date,
                               "start": start, "end": end, "user": user}


def test_reservations_api_filters_by_date(srv):
    assert day(srv, EMPTY_DATE) == []


# ---------------------------------------------------------------- F2 생성
def test_post_creates_and_returns_reservation(srv):
    st, body = post(srv, "C", "09:00", "10:00", "정하늘")
    assert st == 201
    assert body["room_id"] == "C" and body["start"] == "09:00" and body["end"] == "10:00"
    assert body["user"] == "정하늘" and body["date"] == DATE
    assert isinstance(body["res_id"], int)
    assert any(r["res_id"] == body["res_id"] for r in day(srv))


def test_same_slot_on_other_date_is_not_overlap(srv):
    st, _ = post(srv, "A", "10:00", "11:00", date=OTHER_DATE)
    assert st == 201
    assert len(day(srv, OTHER_DATE)) >= 1
    assert len(day(srv)) >= len(RES)


# ---------------------------------------------------------------- R1 30분 단위
@pytest.mark.parametrize("start,end", [("11:15", "12:00"), ("11:00", "11:45"), ("11:10", "11:40")])
def test_r1_not_30_minute_unit_is_400(srv, start, end):
    before = len(day(srv))
    st, body = post(srv, "A", start, end)
    assert st == 400
    assert body["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert len(day(srv)) == before


# ---------------------------------------------------------------- R2 시간대
@pytest.mark.parametrize("start,end", [("08:30", "09:30"), ("17:30", "18:30"), ("18:00", "18:30"), ("08:00", "08:30")])
def test_r2_outside_hours_is_400(srv, start, end):
    before = len(day(srv))
    st, body = post(srv, "B", start, end)
    assert st == 400
    assert body["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert len(day(srv)) == before


@pytest.mark.parametrize("start,end", [("12:00", "12:00"), ("12:30", "12:00")])
def test_r2_end_not_after_start_is_400(srv, start, end):
    before = len(day(srv))
    st, body = post(srv, "B", start, end)
    assert st == 400
    assert body["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert len(day(srv)) == before


def test_r2_boundaries_are_allowed(srv):
    assert post(srv, "B", "09:00", "09:30")[0] == 201
    assert post(srv, "B", "17:30", "18:00")[0] == 201


# ---------------------------------------------------------------- R3 겹침
@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 똑같은 시간
    ("09:30", "10:30"),   # 앞쪽이 걸침
    ("10:30", "11:30"),   # 뒤쪽이 걸침
    ("10:30", "11:00"),   # 안에 쏙 들어감
    ("09:30", "11:30"),   # 통째로 덮음
])
def test_r3_overlap_is_409(srv, start, end):
    before = len(day(srv))
    st, body = post(srv, "A", start, end)
    assert st == 409
    assert body["detail"] == "이미 예약된 시간입니다"
    assert len(day(srv)) == before


def test_r3_adjacent_reservations_are_allowed(srv):
    # A 10:00~11:00 (시드) 의 바로 앞 · 뒤, 그리고 새 예약끼리도 붙여서
    assert post(srv, "A", "09:30", "10:00")[0] == 201
    assert post(srv, "A", "11:00", "11:30")[0] == 201
    assert post(srv, "A", "11:30", "12:00")[0] == 201


def test_r3_overlap_with_newly_created_reservation(srv):
    assert post(srv, "C", "12:00", "13:00")[0] == 201
    st, body = post(srv, "C", "12:30", "13:30", "정하늘")
    assert st == 409 and body["detail"] == "이미 예약된 시간입니다"


# ---------------------------------------------------------------- R4 최대 2시간
def test_r4_exactly_two_hours_ok(srv):
    assert post(srv, "A", "15:00", "17:00")[0] == 201


@pytest.mark.parametrize("room,start,end", [("B", "15:00", "17:30"), ("C", "13:30", "16:00")])
def test_r4_over_two_hours_is_400(srv, room, start, end):
    before = len(day(srv))
    st, body = post(srv, room, start, end)
    assert st == 400
    assert body["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert len(day(srv)) == before


# ---------------------------------------------------------------- R7 다른 방
def test_r7_other_room_same_time_is_independent(srv):
    # A 10:00~11:00 은 시드. B 10:30~11:30 · C 10:00~11:00 은 막히지 않는다.
    assert post(srv, "B", "10:30", "11:30")[0] == 201
    assert post(srv, "C", "10:00", "11:00")[0] == 201


# ---------------------------------------------------------------- 빈 값
@pytest.mark.parametrize("field", ["user", "room_id", "start", "end", "date"])
def test_empty_value_is_400(srv, field):
    body = {"room_id": "B", "date": DATE, "start": "16:00", "end": "16:30", "user": "한도윤"}
    body[field] = ""
    before = len(day(srv))
    st, resp = http("POST", api(srv, "/api/reservations"), body)
    assert st == 400
    assert "detail" in resp
    assert len(day(srv)) == before


# ---------------------------------------------------------------- R5 취소
def test_delete_by_other_user_is_403_and_stays(srv):
    st, body = http("DELETE", api(srv, "/api/reservations/2?user=김민수"))   # 2번은 박지연 것
    assert st == 403
    assert body == {"detail": "본인 예약만 취소할 수 있습니다"}
    assert any(r["res_id"] == 2 for r in day(srv))


def test_delete_without_user_is_403_and_stays(srv):
    st, _ = http("DELETE", api(srv, "/api/reservations/3"))
    assert st == 403
    assert any(r["res_id"] == 3 for r in day(srv))


def test_delete_by_owner_is_204_and_gone(srv):
    st, made = post(srv, "A", "17:00", "17:30", "이서준")
    assert st == 201
    st, _ = http("DELETE", api(srv, "/api/reservations/%d?user=이서준" % made["res_id"]))
    assert st == 204
    assert all(r["res_id"] != made["res_id"] for r in day(srv))
    # 취소한 칸은 다시 예약할 수 있다
    assert post(srv, "A", "17:00", "17:30", "한도윤")[0] == 201


def test_delete_missing_is_404(srv):
    st, _ = http("DELETE", api(srv, "/api/reservations/99999?user=김민수"))
    assert st == 404


# ---------------------------------------------------------------- 화면
SLOT = '[data-testid="slot"]'
CANCEL = '[data-testid="cancel-btn"]'


def slot(page, room, start):
    return page.locator('%s[data-room="%s"][data-start="%s"]' % (SLOT, room, start))


def open_page(pw, srv, date=None, user=None):
    page = pw.new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto(srv.base + "/" + ("?date=" + date if date else ""))
    page.wait_for_selector(SLOT, timeout=5000)
    if user:
        page.select_option('[data-testid="user-select"]', user)
        page.wait_for_timeout(300)
    return page


def test_page_opens_with_title(srv, pw):
    page = pw.new_page()
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("h1")
    page.close()


def test_grid_has_54_slots_with_room_and_time(srv, pw):
    page = open_page(pw, srv)
    assert page.locator(SLOT).count() == 54
    for room, *_ in ROOMS:
        starts = page.locator('%s[data-room="%s"]' % (SLOT, room)).evaluate_all(
            "els => els.map(e => e.dataset.start)")
        assert len(starts) == 18
        assert starts[0] == "09:00" and starts[-1] == "17:30"
        assert starts == sorted(starts)
    page.close()


def test_room_rows_follow_csv_order(srv, pw):
    page = open_page(pw, srv)
    order = page.locator(SLOT).evaluate_all("els => [...new Set(els.map(e => e.dataset.room))]")
    assert order == ["A", "B", "C"]
    page.close()


def test_user_select_options_are_users(srv, pw):
    page = open_page(pw, srv)
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts] == USERS
    page.close()


def test_date_shown_and_query_param_changes_day(srv, pw):
    page = open_page(pw, srv)
    assert DATE in page.inner_text('[data-testid="date"]')
    page.close()
    page = open_page(pw, srv, date=EMPTY_DATE)
    assert EMPTY_DATE in page.inner_text('[data-testid="date"]')
    page.close()


def test_day_without_reservations_is_all_free(srv, pw):
    page = open_page(pw, srv, date=EMPTY_DATE)
    assert page.locator(SLOT).count() == 54
    assert page.locator('%s[data-state="free"]' % SLOT).count() == 54
    page.close()


def test_seed_reservations_show_as_booked(srv, pw):
    page = open_page(pw, srv)
    for room, start in [("A", "10:00"), ("A", "10:30"), ("A", "14:00"), ("B", "10:00"), ("B", "13:00"),
                        ("B", "14:30"), ("C", "16:00"), ("C", "17:30")]:
        assert slot(page, room, start).get_attribute("data-state") == "booked", (room, start)
    # 끝나는 시각의 칸은 비어 있다
    for room, start in [("A", "11:00"), ("A", "14:30"), ("B", "10:30"), ("B", "15:00")]:
        assert slot(page, room, start).get_attribute("data-state") == "free", (room, start)
    page.close()


def test_booked_slot_shows_user_name(srv, pw):
    page = open_page(pw, srv)
    assert "박지연" in slot(page, "A", "14:00").inner_text()
    assert "이서준" in slot(page, "B", "10:00").inner_text()
    page.close()


def test_mine_state_for_selected_user(srv, pw):
    page = open_page(pw, srv, user="김민수")
    for room, start in [("A", "10:00"), ("A", "10:30"), ("B", "13:00"), ("B", "14:30")]:
        assert slot(page, room, start).get_attribute("data-state") == "mine", (room, start)
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    assert "김민수" in slot(page, "A", "10:00").inner_text()
    page.close()


def test_changing_user_changes_mine(srv, pw):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.select_option('[data-testid="user-select"]', "박지연")
    page.wait_for_timeout(300)
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    page.close()


def test_cancel_button_only_on_mine(srv, pw):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").locator(CANCEL).count() >= 1
    assert slot(page, "A", "14:00").locator(CANCEL).count() == 0   # 남의 예약
    assert slot(page, "A", "09:00").locator(CANCEL).count() == 0   # 빈 칸
    assert page.locator('%s[data-state="booked"] %s' % (SLOT, CANCEL)).count() == 0
    page.close()


def test_cancel_via_ui_removes_reservation(srv, pw):
    st, made = post(srv, "C", "13:00", "13:30", "김민수")
    assert st == 201
    page = open_page(pw, srv, user="김민수")
    s = slot(page, "C", "13:00")
    assert s.get_attribute("data-state") == "mine"
    s.locator(CANCEL).first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=C][data-start=\"13:00\"]').dataset.state === 'free'",
        timeout=5000)
    assert all(r["res_id"] != made["res_id"] for r in day(srv))
    page.close()


def test_error_state_when_api_fails(srv, pw):
    page = pw.new_page()
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/")
    page.wait_for_timeout(1000)
    assert "불러오지 못했습니다" in page.inner_text("body")
    page.close()


def test_message_line_exists(srv, pw):
    page = open_page(pw, srv)
    assert page.locator('[data-testid="message"]').count() == 1
    page.close()
