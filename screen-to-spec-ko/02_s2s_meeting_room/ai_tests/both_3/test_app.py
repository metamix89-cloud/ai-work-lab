# -*- coding: utf-8 -*-
"""PRD.md 기준 테스트. 서버는 모듈 안에서 공유되므로, 예약을 만드는 테스트는 날짜를 따로 쓴다."""
import itertools

import pytest

from conftest import DATE, RES, ROOMS, USERS, http

_days = itertools.count(1)


def fresh_date():
    """다른 테스트와 겹치지 않는 새 날짜 (고정 데이터에는 없는 날)."""
    return "2027-01-%02d" % next(_days)


def body(start, end, room="A", date=DATE, user="김민수"):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def post(srv, **kw):
    return http("POST", srv.base + "/api/reservations", body(**kw))


def listing(srv, date):
    st, data = http("GET", srv.base + "/api/reservations?date=" + date)
    assert st == 200
    return data


# ---------- F5 조회 API ----------

def test_rooms_api(srv):
    st, data = http("GET", srv.base + "/api/rooms")
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_reservations_api_returns_seed_for_date(srv):
    data = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_reservations_api_other_date_is_empty(srv):
    assert listing(srv, "2030-05-05") == []


# ---------- F2 / 생성 ----------

def test_create_returns_201_and_item(srv):
    d = fresh_date()
    st, item = post(srv, start="09:00", end="10:00", date=d, user="박지연")
    assert st == 201
    assert item["room_id"] == "A" and item["date"] == d
    assert (item["start"], item["end"], item["user"]) == ("09:00", "10:00", "박지연")
    assert isinstance(item["res_id"], int)
    assert any(r["res_id"] == item["res_id"] for r in listing(srv, d))


# ---------- R1 30분 단위 ----------

@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("09:00", "10:10"), ("09:45", "10:15")])
def test_r1_not_30min_unit_is_400(srv, start, end):
    d = fresh_date()
    st, res = post(srv, start=start, end=end, date=d)
    assert st == 400
    assert res["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv, d) == []


# ---------- R2 09:00~18:00 ----------

@pytest.mark.parametrize("start,end", [("17:30", "18:30"), ("08:30", "09:30"), ("10:00", "10:00"), ("11:00", "10:30")])
def test_r2_outside_hours_or_inverted_is_400(srv, start, end):
    d = fresh_date()
    st, res = post(srv, start=start, end=end, date=d)
    assert st == 400
    assert res["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv, d) == []


def test_r2_boundaries_are_allowed(srv):
    d = fresh_date()
    assert post(srv, start="09:00", end="09:30", date=d)[0] == 201
    assert post(srv, start="17:30", end="18:00", date=d)[0] == 201


# ---------- R3 겹침 ----------

@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 완전 일치
    ("10:30", "11:30"),   # 뒤쪽 걸침
    ("09:30", "10:30"),   # 앞쪽 걸침
    ("10:30", "11:00"),   # 안에 포함
])
def test_r3_overlap_is_409_and_count_unchanged(srv, start, end):
    before = listing(srv, DATE)
    st, res = post(srv, start=start, end=end)   # A 10:00~11:00 (김민수 예약) 과 겹침
    assert st == 409
    assert res["detail"] == "이미 예약된 시간입니다"
    assert len(listing(srv, DATE)) == len(before)


def test_r3_enclosing_overlap_is_409(srv):
    before = len(listing(srv, DATE))
    st, res = post(srv, start="13:30", end="14:30", user="정하늘")   # A 14:00~14:30 을 끝까지 걸침
    assert st == 409 and res["detail"] == "이미 예약된 시간입니다"
    st, res = post(srv, start="09:00", end="11:00", room="B", user="정하늘")  # B 10:00~10:30 을 감쌈
    assert st == 409 and res["detail"] == "이미 예약된 시간입니다"
    assert len(listing(srv, DATE)) == before


def test_r3_back_to_back_is_allowed(srv):
    d = fresh_date()
    assert post(srv, start="10:00", end="10:30", date=d)[0] == 201
    assert post(srv, start="10:30", end="11:00", date=d, user="박지연")[0] == 201   # 뒤에 붙임
    assert post(srv, start="09:30", end="10:00", date=d, user="이서준")[0] == 201   # 앞에 붙임
    assert len(listing(srv, d)) == 3


def test_r3_back_to_back_with_seed_reservation(srv):
    """고정 데이터 C 16:00~18:00 바로 앞에 붙여 예약."""
    st, _ = post(srv, room="C", start="15:30", end="16:00", user="정하늘")
    assert st == 201


# ---------- R4 최대 2시간 ----------

def test_r4_over_two_hours_is_400(srv):
    d = fresh_date()
    st, res = post(srv, start="09:00", end="11:30", date=d)
    assert st == 400
    assert res["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert listing(srv, d) == []


def test_r4_exactly_two_hours_is_201(srv):
    d = fresh_date()
    assert post(srv, start="09:00", end="11:00", date=d)[0] == 201


def test_r4_two_hours_plus_30min_boundary(srv):
    d = fresh_date()
    assert post(srv, start="13:00", end="15:30", date=d)[0] == 400
    assert post(srv, start="13:00", end="15:00", date=d)[0] == 201


# ---------- R7 회의실 · 날짜 독립 ----------

def test_r7_other_room_same_time_is_independent(srv):
    d = fresh_date()
    assert post(srv, room="A", start="10:00", end="11:00", date=d)[0] == 201
    assert post(srv, room="B", start="10:00", end="11:00", date=d, user="박지연")[0] == 201
    assert post(srv, room="C", start="10:00", end="11:00", date=d, user="이서준")[0] == 201


def test_other_date_same_room_same_time_is_independent(srv):
    d = fresh_date()
    assert post(srv, room="A", start="10:00", end="11:00", date=d)[0] == 201   # DATE 의 A 10:00 과 무관


# ---------- F3 / R5 취소 ----------

def delete(srv, res_id, user):
    return http("DELETE", srv.base + "/api/reservations/%s?user=%s" % (res_id, user))


def test_r5_delete_others_is_403_and_remains(srv):
    d = fresh_date()
    _, item = post(srv, start="10:00", end="11:00", date=d, user="김민수")
    st, res = delete(srv, item["res_id"], "박지연")
    assert st == 403
    assert res["detail"] == "본인 예약만 취소할 수 있습니다"
    assert any(r["res_id"] == item["res_id"] for r in listing(srv, d))


def test_r5_delete_own_is_204_and_gone(srv):
    d = fresh_date()
    _, item = post(srv, start="10:00", end="11:00", date=d, user="김민수")
    st, res = delete(srv, item["res_id"], "김민수")
    assert st == 204
    assert not res
    assert listing(srv, d) == []


def test_r5_delete_without_user_is_rejected(srv):
    d = fresh_date()
    _, item = post(srv, start="10:00", end="11:00", date=d, user="김민수")
    st, _ = http("DELETE", srv.base + "/api/reservations/%s" % item["res_id"])
    assert st == 403
    assert len(listing(srv, d)) == 1


def test_delete_missing_is_404(srv):
    st, _ = delete(srv, 99999, "김민수")
    assert st == 404


def test_cancelled_slot_can_be_booked_again(srv):
    d = fresh_date()
    _, item = post(srv, start="10:00", end="11:00", date=d, user="김민수")
    assert delete(srv, item["res_id"], "김민수")[0] == 204
    assert post(srv, start="10:00", end="11:00", date=d, user="박지연")[0] == 201


# ---------- 화면 ----------

def open_page(pw, srv, date=DATE, user=None):
    page = pw.new_page()
    page.goto(srv.base + "/?date=" + date)
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', user)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_ui_page_opens_with_title(pw, srv):
    page = pw.new_page()
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("h1")
    page.close()


def test_ui_has_54_slots(pw, srv):
    page = open_page(pw, srv)
    assert page.locator('[data-testid="slot"]').count() == 3 * 18
    for room, _, _ in ROOMS:
        assert page.locator('[data-testid="slot"][data-room="%s"]' % room).count() == 18
    assert slot(page, "A", "09:00").count() == 1
    assert slot(page, "A", "17:30").count() == 1
    page.close()


def test_ui_date_is_shown(pw, srv):
    page = open_page(pw, srv)
    assert DATE in page.inner_text('[data-testid="date"]')
    page.close()


def test_ui_user_select_options_are_users(pw, srv):
    page = open_page(pw, srv)
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts] == USERS
    page.close()


def test_ui_booked_slots_for_other_user(pw, srv):
    page = open_page(pw, srv, user="박지연")
    for start in ("10:00", "10:30"):
        s = slot(page, "A", start)
        assert s.get_attribute("data-state") == "booked"
        assert "김민수" in s.inner_text()
    page.close()


def test_ui_mine_slots_for_owner(pw, srv):
    page = open_page(pw, srv, user="김민수")
    for start in ("10:00", "10:30"):
        assert slot(page, "A", start).get_attribute("data-state") == "mine"
    page.close()


def test_ui_free_slot_state(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "09:00").get_attribute("data-state") == "free"
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"   # 끝 시각 칸은 비어 있다
    assert slot(page, "C", "09:00").get_attribute("data-state") == "free"
    page.close()


def test_ui_seed_slot_states_match_seed(pw, srv):
    """고정 데이터 전체가 칸 상태로 정확히 그려진다 (김민수 기준)."""
    # 이전 테스트들이 DATE 에 예약을 더했을 수 있으므로 서버 목록을 기준으로 삼는다.
    data = listing(srv, DATE)
    page = open_page(pw, srv, user="김민수")

    def mins(t):
        return int(t[:2]) * 60 + int(t[3:])
    for room, _, _ in ROOMS:
        for m in range(9 * 60, 18 * 60, 30):
            start = "%02d:%02d" % (m // 60, m % 60)
            hit = [r for r in data if r["room_id"] == room and mins(r["start"]) <= m < mins(r["end"])]
            want = "free" if not hit else ("mine" if hit[0]["user"] == "김민수" else "booked")
            assert slot(page, room, start).get_attribute("data-state") == want, (room, start)
    page.close()


def test_ui_changing_user_changes_mine(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.select_option('[data-testid="user-select"]', "박지연")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.close()


def test_ui_cancel_button_only_on_mine(pw, srv):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "B", "13:00").locator('[data-testid="cancel-btn"]').count() >= 1   # 김민수의 다른 예약
    for room, start in (("A", "14:00"), ("B", "10:00"), ("C", "16:00")):   # 남의 예약
        s = slot(page, room, start)
        assert s.get_attribute("data-state") == "booked"
        assert s.locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0   # 빈 칸
    page.close()


def test_ui_no_cancel_buttons_for_user_without_reservations(pw, srv):
    page = open_page(pw, srv, user="한도윤")
    assert page.locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_ui_cancel_removes_reservation(pw, srv):
    d = fresh_date()
    _, item = post(srv, room="C", start="12:00", end="12:30", date=d, user="이서준")
    page = open_page(pw, srv, date=d, user="이서준")
    s = slot(page, "C", "12:00")
    assert s.get_attribute("data-state") == "mine"
    s.locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=C][data-start=\"12:00\"]')"
        ".getAttribute('data-state') === 'free'")
    assert listing(srv, d) == []
    page.close()


def test_ui_date_param_shows_other_day(pw, srv):
    d = fresh_date()
    post(srv, room="B", start="09:00", end="09:30", date=d, user="최유나")
    page = open_page(pw, srv, date=d, user="최유나")
    assert d in page.inner_text('[data-testid="date"]')
    assert slot(page, "B", "09:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:00").get_attribute("data-state") == "free"   # DATE 의 예약은 안 보인다
    page.close()


def test_ui_message_element_exists(pw, srv):
    page = open_page(pw, srv)
    assert page.locator('[data-testid="message"]').count() == 1
    page.close()
