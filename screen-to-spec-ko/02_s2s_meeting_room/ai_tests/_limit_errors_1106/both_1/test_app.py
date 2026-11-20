# -*- coding: utf-8 -*-
"""PRD.md 기준 테스트. 서버 상태가 모듈 안에서 이어지므로, 상태를 바꾸는 테스트는 저마다 다른 날짜를 쓴다."""
import pytest

from conftest import DATE, RES, ROOMS, USERS, http

SLOTS = 18


def url(srv, path):
    return srv.base + path


def post(srv, room, date, start, end, user="박지연"):
    return http("POST", url(srv, "/api/reservations"),
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def listing(srv, date):
    status, body = http("GET", url(srv, "/api/reservations?date=" + date))
    assert status == 200
    return body


# ---------- API: 조회 (F5) ----------

def test_rooms_api(srv):
    status, body = http("GET", url(srv, "/api/rooms"))
    assert status == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in body] == ROOMS


def test_reservations_api_returns_seed_for_date(srv):
    body = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in body)
    assert got == sorted(RES)


def test_reservations_api_filters_by_date(srv):
    assert listing(srv, "2030-01-01") == []


# ---------- R1 30분 단위 ----------

@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("10:10", "10:40")])
def test_r1_not_30min_unit_is_400(srv, start, end):
    status, body = post(srv, "C", "2027-01-01", start, end)
    assert status == 400
    assert body["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv, "2027-01-01") == []


# ---------- R2 09:00~18:00 ----------

@pytest.mark.parametrize("start,end", [("17:30", "18:30"), ("08:30", "09:30"), ("10:00", "10:00"), ("11:00", "10:30")])
def test_r2_out_of_hours_or_inverted_is_400(srv, start, end):
    status, body = post(srv, "C", "2027-01-02", start, end)
    assert status == 400
    assert body["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv, "2027-01-02") == []


def test_r2_boundaries_allowed(srv):
    assert post(srv, "C", "2027-01-03", "09:00", "09:30")[0] == 201
    assert post(srv, "C", "2027-01-03", "17:30", "18:00")[0] == 201


# ---------- R3 겹침 ----------

@pytest.mark.parametrize("start,end", [("10:00", "11:00"), ("10:30", "11:30"), ("09:30", "10:30"), ("10:30", "11:00"), ("09:30", "11:30")])
def test_r3_overlap_is_409_and_count_unchanged(srv, start, end):
    before = listing(srv, DATE)
    status, body = post(srv, "A", DATE, start, end)
    assert status == 409
    assert body["detail"] == "이미 예약된 시간입니다"
    assert len(listing(srv, DATE)) == len(before)


def test_r3_adjacent_reservations_are_allowed(srv):
    d = "2027-01-04"
    assert post(srv, "A", d, "10:00", "10:30")[0] == 201
    assert post(srv, "A", d, "10:30", "11:00")[0] == 201  # 앞 예약의 끝 = 시작
    assert post(srv, "A", d, "09:30", "10:00")[0] == 201  # 뒤 예약의 시작 = 끝
    assert len(listing(srv, d)) == 3


def test_r3_adjacent_to_seed_reservation(srv):
    # 시드 A 10:00~11:00 바로 앞뒤
    d = DATE
    assert post(srv, "A", d, "09:00", "10:00", "이서준")[0] == 201
    assert post(srv, "A", d, "11:00", "12:00", "이서준")[0] == 201


def test_r3_same_slot_twice_conflicts(srv):
    d = "2027-01-05"
    assert post(srv, "B", d, "12:00", "13:00")[0] == 201
    assert post(srv, "B", d, "12:00", "13:00")[0] == 409


def test_r3_different_date_does_not_conflict(srv):
    assert post(srv, "A", "2027-01-06", "10:00", "11:00")[0] == 201


# ---------- R7 회의실 독립 ----------

def test_r7_other_room_same_time_is_allowed(srv):
    d = "2027-01-07"
    assert post(srv, "A", d, "10:00", "11:00")[0] == 201
    assert post(srv, "B", d, "10:00", "11:00")[0] == 201
    assert post(srv, "C", d, "10:00", "11:00")[0] == 201


# ---------- R4 최대 2시간 ----------

def test_r4_two_hours_ok_and_response_body(srv):
    status, body = post(srv, "C", "2027-01-08", "09:00", "11:00", "한도윤")
    assert status == 201
    assert (body["room_id"], body["date"], body["start"], body["end"], body["user"]) == ("C", "2027-01-08", "09:00", "11:00", "한도윤")
    assert "res_id" in body


@pytest.mark.parametrize("start,end", [("09:00", "11:30"), ("09:00", "17:00")])
def test_r4_over_two_hours_is_400(srv, start, end):
    status, body = post(srv, "C", "2027-01-09", start, end)
    assert status == 400
    assert body["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert listing(srv, "2027-01-09") == []


# ---------- R5 취소는 본인만 ----------

def test_r5_delete_others_is_403_and_remains(srv):
    status, body = http("DELETE", url(srv, "/api/reservations/1?user=" + "박지연"))
    assert status == 403
    assert body["detail"] == "본인 예약만 취소할 수 있습니다"
    assert any(r["res_id"] == 1 for r in listing(srv, DATE))


def test_r5_delete_own_is_204_and_gone(srv):
    status, body = post(srv, "C", "2027-01-10", "09:00", "10:00", "정하늘")
    assert status == 201
    rid = body["res_id"]
    status, _ = http("DELETE", url(srv, "/api/reservations/%d?user=정하늘" % rid))
    assert status == 204
    assert listing(srv, "2027-01-10") == []


def test_r5_delete_missing_is_404(srv):
    status, _ = http("DELETE", url(srv, "/api/reservations/99999?user=김민수"))
    assert status == 404


def test_r5_cancel_frees_the_time(srv):
    d = "2027-01-11"
    rid = post(srv, "B", d, "14:00", "15:00", "정하늘")[1]["res_id"]
    assert post(srv, "B", d, "14:00", "15:00")[0] == 409
    assert http("DELETE", url(srv, "/api/reservations/%d?user=정하늘" % rid))[0] == 204
    assert post(srv, "B", d, "14:00", "15:00")[0] == 201


# ---------- 화면 ----------

def open_page(pw, srv, date=None, user=None):
    page = pw.new_page()
    page.goto(srv.base + "/" + ("?date=" + date if date else ""))
    page.wait_for_selector('[data-testid="slot"]', timeout=5000)
    if user:
        page.select_option('[data-testid="user-select"]', label=user)
        page.wait_for_timeout(300)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_t1_page_opens_with_title(pw, srv):
    status, body = http("GET", srv.base + "/")
    assert status == 200
    assert "회의실" in body
    page = open_page(pw, srv)
    assert "다온소프트 회의실 예약" in page.inner_text("body")
    page.close()


def test_t2_54_slots_with_3_rooms_by_18(pw, srv):
    page = open_page(pw, srv, DATE)
    assert page.locator('[data-testid="slot"]').count() == len(ROOMS) * SLOTS
    for room, _, _ in ROOMS:
        assert page.locator('[data-testid="slot"][data-room="%s"]' % room).count() == SLOTS
    assert slot(page, "A", "09:00").count() == 1
    assert slot(page, "C", "17:30").count() == 1
    page.close()


def test_date_shown_and_selected_by_query(pw, srv):
    page = open_page(pw, srv, DATE)
    assert DATE in page.inner_text('[data-testid="date"]')
    page.close()


def test_user_select_options_match_users(pw, srv):
    page = open_page(pw, srv, DATE)
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts] == USERS
    page.close()


def test_t3_seed_reservations_show_as_booked_then_mine(pw, srv):
    page = open_page(pw, srv, DATE, user="박지연")
    for start in ("10:00", "10:30"):
        assert slot(page, "A", start).get_attribute("data-state") == "booked"
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"
    assert "김민수" in slot(page, "A", "10:00").inner_text()
    page.select_option('[data-testid="user-select"]', label="김민수")
    page.wait_for_timeout(300)
    for start in ("10:00", "10:30"):
        assert slot(page, "A", start).get_attribute("data-state") == "mine"
    # 박지연의 A 14:00 은 김민수에게 booked
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.close()


def test_r6_switching_user_changes_mine(pw, srv):
    page = open_page(pw, srv, DATE, user="김민수")
    assert slot(page, "B", "13:00").get_attribute("data-state") == "mine"
    assert slot(page, "B", "10:00").get_attribute("data-state") == "booked"
    page.select_option('[data-testid="user-select"]', label="이서준")
    page.wait_for_timeout(300)
    assert slot(page, "B", "13:00").get_attribute("data-state") == "booked"
    assert slot(page, "B", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    page.close()


def test_free_slots_everywhere_else(pw, srv):
    page = open_page(pw, srv, "2030-01-01", user="김민수")
    states = {s.get_attribute("data-state") for s in page.locator('[data-testid="slot"]').all()}
    assert states == {"free"}
    page.close()


def test_t9_cancel_button_only_on_mine(pw, srv):
    page = open_page(pw, srv, DATE, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "B", "13:00").locator('[data-testid="cancel-btn"]').count() >= 1
    for room, start in (("A", "14:00"), ("B", "10:00"), ("C", "16:00")):
        s = slot(page, room, start)
        assert s.get_attribute("data-state") == "booked"
        assert s.locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_ui_cancel_button_removes_reservation(pw, srv):
    d = "2027-02-01"
    assert post(srv, "C", d, "11:00", "11:30", "최유나")[0] == 201
    page = open_page(pw, srv, d, user="최유나")
    assert slot(page, "C", "11:00").get_attribute("data-state") == "mine"
    slot(page, "C", "11:00").locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_timeout(500)
    assert slot(page, "C", "11:00").get_attribute("data-state") == "free"
    assert listing(srv, d) == []
    page.close()


def test_ui_new_reservation_visible_after_post(pw, srv):
    d = "2027-02-02"
    assert post(srv, "B", d, "09:00", "10:00", "정하늘")[0] == 201
    page = open_page(pw, srv, d, user="한도윤")
    for start in ("09:00", "09:30"):
        assert slot(page, "B", start).get_attribute("data-state") == "booked"
    assert slot(page, "B", "10:00").get_attribute("data-state") == "free"
    page.close()
