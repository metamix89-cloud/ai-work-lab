# -*- coding: utf-8 -*-
"""PRD.md 기준 테스트. 서버는 모듈 내내 하나라 상태가 공유된다 -> 변경 테스트는 DATE 가 아닌 전용 날짜를 쓴다."""
import itertools

import pytest

from conftest import DATE, RES, ROOMS, USERS, http

_days = itertools.count(1)


def fresh_date():
    """테스트마다 겹치지 않는 빈 날짜 (고정 데이터는 DATE 에만 있다)."""
    return "2027-01-%02d" % next(_days)


def book(srv, room, date, start, end, user="김민수"):
    return http("POST", srv.base + "/api/reservations",
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def listing(srv, date):
    st, data = http("GET", srv.base + "/api/reservations?date=" + date)
    assert st == 200
    return data


# ---------------- API: 조회 ----------------

def test_rooms_api(srv):
    st, data = http("GET", srv.base + "/api/rooms")
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_reservations_api_returns_seed_for_date(srv):
    data = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_reservations_api_filters_by_date(srv):
    assert listing(srv, fresh_date()) == []


# ---------------- API: 예약 생성 / 규칙 ----------------

def test_create_returns_201_and_reservation(srv):
    d = fresh_date()
    st, body = book(srv, "A", d, "13:00", "14:00", "박지연")
    assert st == 201
    assert (body["room_id"], body["date"], body["start"], body["end"], body["user"]) == ("A", d, "13:00", "14:00", "박지연")
    assert isinstance(body["res_id"], int)
    assert any(r["res_id"] == body["res_id"] for r in listing(srv, d))


def test_r3_overlap_is_409_and_count_unchanged(srv):
    d = fresh_date()
    assert book(srv, "A", d, "10:00", "11:00")[0] == 201
    before = len(listing(srv, d))
    st, body = book(srv, "A", d, "10:30", "11:30", "박지연")
    assert st == 409
    assert body["detail"] == "이미 예약된 시간입니다"
    assert len(listing(srv, d)) == before


@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 완전 동일
    ("09:30", "10:30"),   # 앞쪽 걸침
    ("10:30", "11:30"),   # 뒤쪽 걸침
    ("10:30", "11:00"),   # 안에 포함
    ("09:30", "11:30"),   # 감쌈
])
def test_r3_overlap_variants_rejected(srv, start, end):
    d = fresh_date()
    assert book(srv, "A", d, "10:00", "11:00")[0] == 201
    assert book(srv, "A", d, start, end, "박지연")[0] == 409


def test_r3_adjacent_reservations_allowed(srv):
    d = fresh_date()
    assert book(srv, "A", d, "10:00", "10:30")[0] == 201
    assert book(srv, "A", d, "10:30", "11:00", "박지연")[0] == 201   # 뒤에 붙임
    assert book(srv, "A", d, "09:30", "10:00", "이서준")[0] == 201   # 앞에 붙임


def test_r7_other_room_same_time_independent(srv):
    d = fresh_date()
    assert book(srv, "A", d, "10:00", "11:00")[0] == 201
    assert book(srv, "B", d, "10:00", "11:00", "박지연")[0] == 201


def test_r3_other_date_same_time_independent(srv):
    d1, d2 = fresh_date(), fresh_date()
    assert book(srv, "A", d1, "10:00", "11:00")[0] == 201
    assert book(srv, "A", d2, "10:00", "11:00", "박지연")[0] == 201


@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("10:10", "10:50")])
def test_r1_not_30min_unit_is_400(srv, start, end):
    d = fresh_date()
    st, body = book(srv, "A", d, start, end)
    assert st == 400
    assert body["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv, d) == []


@pytest.mark.parametrize("start,end", [
    ("17:30", "18:30"),   # 끝이 18:00 초과
    ("08:30", "09:30"),   # 시작이 09:00 이전
    ("11:00", "10:30"),   # end < start
    ("11:00", "11:00"),   # end == start
])
def test_r2_outside_hours_or_inverted_is_400(srv, start, end):
    d = fresh_date()
    st, body = book(srv, "A", d, start, end)
    assert st == 400
    assert body["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv, d) == []


def test_r2_boundaries_allowed(srv):
    d = fresh_date()
    assert book(srv, "A", d, "09:00", "09:30")[0] == 201
    assert book(srv, "A", d, "17:30", "18:00", "박지연")[0] == 201


def test_r4_over_two_hours_is_400(srv):
    d = fresh_date()
    st, body = book(srv, "A", d, "09:00", "11:30")
    assert st == 400
    assert body["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert listing(srv, d) == []


def test_r4_exactly_two_hours_is_201(srv):
    assert book(srv, "A", fresh_date(), "09:00", "11:00")[0] == 201


def test_empty_value_is_400(srv):
    d = fresh_date()
    st, body = book(srv, "A", d, "10:00", "11:00", "")
    assert st == 400
    assert "detail" in body
    assert listing(srv, d) == []


# ---------------- API: 취소 ----------------

def test_r5_delete_by_other_is_403_and_remains(srv):
    d = fresh_date()
    _, made = book(srv, "A", d, "10:00", "11:00", "김민수")
    st, body = http("DELETE", "%s/api/reservations/%d?user=박지연" % (srv.base, made["res_id"]))
    assert st == 403
    assert body["detail"] == "본인 예약만 취소할 수 있습니다"
    assert any(r["res_id"] == made["res_id"] for r in listing(srv, d))


def test_delete_without_user_is_403(srv):
    d = fresh_date()
    _, made = book(srv, "A", d, "10:00", "11:00", "김민수")
    st, _ = http("DELETE", "%s/api/reservations/%d" % (srv.base, made["res_id"]))
    assert st == 403
    assert len(listing(srv, d)) == 1


def test_delete_by_owner_is_204_and_gone(srv):
    d = fresh_date()
    _, made = book(srv, "A", d, "10:00", "11:00", "김민수")
    st, body = http("DELETE", "%s/api/reservations/%d?user=김민수" % (srv.base, made["res_id"]))
    assert st == 204
    assert not body
    assert listing(srv, d) == []


def test_delete_frees_slot_for_rebooking(srv):
    d = fresh_date()
    _, made = book(srv, "A", d, "10:00", "11:00", "김민수")
    http("DELETE", "%s/api/reservations/%d?user=김민수" % (srv.base, made["res_id"]))
    assert book(srv, "A", d, "10:00", "11:00", "박지연")[0] == 201


def test_delete_missing_is_404(srv):
    st, _ = http("DELETE", srv.base + "/api/reservations/99999?user=김민수")
    assert st == 404


# ---------------- 화면 ----------------

def open_page(pw, srv, date=DATE, user=None):
    page = pw.new_page()
    page.goto("%s/?date=%s" % (srv.base, date))
    page.wait_for_selector('[data-testid="slot"]', timeout=5000)
    if user:
        page.select_option('[data-testid="user-select"]', user)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_t1_root_opens_with_title(srv, pw):
    page = pw.new_page()
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("h1")
    page.close()


def test_t2_grid_has_54_slots(srv, pw):
    page = open_page(pw, srv)
    assert page.locator('[data-testid="slot"]').count() == 54
    for room, _, _ in ROOMS:
        assert page.locator('[data-testid="slot"][data-room="%s"]' % room).count() == 18
    starts = page.locator('[data-testid="slot"][data-room="A"]').evaluate_all("els => els.map(e => e.dataset.start)")
    assert starts[0] == "09:00" and starts[-1] == "17:30" and len(set(starts)) == 18
    page.close()


def test_date_element_shows_date(srv, pw):
    page = open_page(pw, srv)
    assert DATE in page.inner_text('[data-testid="date"]')
    page.close()


def test_user_select_options_match_users(srv, pw):
    page = open_page(pw, srv)
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts] == USERS
    page.close()


def test_t3_seed_reservations_shown_as_booked(srv, pw):
    page = open_page(pw, srv)
    for room, start in [("A", "10:00"), ("A", "10:30"), ("A", "14:00"), ("B", "10:00"),
                        ("C", "16:00"), ("C", "17:30")]:
        assert slot(page, room, start).get_attribute("data-state") in ("booked", "mine")
    assert slot(page, "A", "09:00").get_attribute("data-state") == "free"
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"   # 끝 시각 칸은 비어 있다
    assert slot(page, "A", "14:30").get_attribute("data-state") == "free"
    page.close()


def test_booked_slot_shows_user_name(srv, pw):
    page = open_page(pw, srv, user="박지연")
    assert "김민수" in slot(page, "A", "10:00").inner_text()
    assert "이서준" in slot(page, "B", "10:00").inner_text()
    page.close()


def test_t3_r6_mine_follows_selected_user(srv, pw):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:30").get_attribute("data-state") == "mine"
    assert slot(page, "B", "13:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.select_option('[data-testid="user-select"]', "박지연")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    assert slot(page, "B", "13:00").get_attribute("data-state") == "booked"
    page.close()


def test_t9_cancel_button_only_on_mine(srv, pw):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() == 0   # 남의 예약
    assert slot(page, "B", "10:00").locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0   # 빈 칸
    page.close()


def test_free_slot_has_no_cancel_button_and_no_name(srv, pw):
    page = open_page(pw, srv, user="김민수")
    free = slot(page, "C", "09:00")
    assert free.get_attribute("data-state") == "free"
    assert free.locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_f4_date_param_switches_day(srv, pw):
    d = fresh_date()
    page = open_page(pw, srv, date=d)
    assert d in page.inner_text('[data-testid="date"]')
    assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54
    page.close()


def test_cancel_button_removes_own_reservation(srv, pw):
    d = fresh_date()
    assert book(srv, "C", d, "11:00", "11:30", "김민수")[0] == 201
    page = open_page(pw, srv, date=d, user="김민수")
    assert slot(page, "C", "11:00").get_attribute("data-state") == "mine"
    page.once("dialog", lambda dlg: dlg.accept())   # confirm 이 있어도 통과
    slot(page, "C", "11:00").locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=C][data-start=\"11:00\"]').dataset.state === 'free'",
        timeout=5000)
    assert listing(srv, d) == []
    page.close()


def test_booking_via_form_creates_reservation(srv, pw):
    d = fresh_date()
    page = open_page(pw, srv, date=d, user="박지연")
    slot(page, "B", "15:00").click()
    # 폼 필드 손잡이는 PRD 에 없다 -> 끝 선택(select)에서 60분에 해당하는 옵션을 고르고 제출 버튼을 누른다.
    form_select = page.locator("select").filter(has_not=page.locator('[data-testid="user-select"]'))
    page.wait_for_timeout(300)
    if form_select.count():
        sel = form_select.last
        labels = sel.locator("option").all_inner_texts()
        pick = next((i for i, t in enumerate(labels) if "60" in t or "16:00" in t or "1시간" in t), None)
        assert pick is not None, "끝 선택 옵션에 60분(16:00)이 없다: %s" % labels
        sel.select_option(index=pick)
    page.get_by_role("button", name="예약").last.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=B][data-start=\"15:00\"]').dataset.state === 'mine'",
        timeout=5000)
    got = listing(srv, d)
    assert [(r["room_id"], r["start"], r["end"], r["user"]) for r in got] == [("B", "15:00", "16:00", "박지연")]
    page.close()


def test_error_state_when_api_fails(srv, pw):
    page = pw.new_page()
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/?date=" + DATE)
    page.wait_for_selector("text=불러오지 못했습니다", timeout=5000)
    assert page.get_by_role("button", name="다시").count() >= 1
    page.close()
