# -*- coding: utf-8 -*-
"""다온소프트 회의실 예약 — PRD.md 기준 테스트.

서버는 모듈 안에서 공유되므로, 예약을 바꾸는 테스트는 서로 다른 날짜(시드가 없는 날)를 써서
서로 영향을 주지 않게 한다. 시드 날짜(DATE)는 읽기 전용으로만 쓴다.
"""
import urllib.parse

import pytest

from conftest import DATE, ROOMS, USERS, RES, http

pytestmark = pytest.mark.filterwarnings("ignore")


def api(srv, path):
    return srv.base + path


def body(room="A", date="2030-01-01", start="13:00", end="14:00", user="박지연"):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def delurl(srv, res_id, user):
    return srv.base + "/api/reservations/%d?user=%s" % (res_id, urllib.parse.quote(user))


def post(srv, **kw):
    return http("POST", api(srv, "/api/reservations"), body(**kw))


def listing(srv, date):
    st, data = http("GET", api(srv, "/api/reservations?date=" + date))
    assert st == 200
    return data


# ---------------------------------------------------------------- API: 조회 (F5)

def test_rooms_api(srv):
    st, data = http("GET", api(srv, "/api/rooms"))
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_reservations_list_seed(srv):
    data = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_reservations_list_other_date_empty(srv):
    assert listing(srv, "2030-02-02") == []


def test_users_api_if_present(srv):
    """PRD 에는 없지만 사용자 선택 상자를 채우려면 필요. 있다면 이름이 시드와 같아야 한다."""
    st, data = http("GET", api(srv, "/api/users"))
    if st == 404:
        pytest.skip("/api/users 없음 (PRD 범위 밖)")
    assert st == 200
    names = [u["user"] if isinstance(u, dict) else u for u in data]
    assert names == USERS


# ---------------------------------------------------------------- API: 생성 (F2, R1~R4, R7)

def test_create_ok_returns_201_and_reservation(srv):
    st, data = post(srv, date="2030-03-01")
    assert st == 201
    assert data["room_id"] == "A" and data["date"] == "2030-03-01"
    assert data["start"] == "13:00" and data["end"] == "14:00" and data["user"] == "박지연"
    assert isinstance(data["res_id"], int)
    assert any(r["res_id"] == data["res_id"] for r in listing(srv, "2030-03-01"))


def test_created_ids_are_unique(srv):
    _, a = post(srv, date="2030-03-02", start="09:00", end="09:30")
    _, b = post(srv, date="2030-03-02", start="09:30", end="10:00")
    assert a["res_id"] != b["res_id"]


def test_overlap_same_slot_409(srv):
    assert post(srv, date="2030-03-03")[0] == 201
    st, data = post(srv, date="2030-03-03", user="이서준")
    assert st == 409
    assert data["detail"] == "이미 예약된 시간입니다"
    assert len(listing(srv, "2030-03-03")) == 1


def test_overlap_against_seed_409_count_unchanged(srv):
    before = len(listing(srv, DATE))
    st, data = post(srv, date=DATE, start="10:30", end="11:30")  # A 10:00~11:00 과 겹침
    assert st == 409 and data["detail"] == "이미 예약된 시간입니다"
    assert len(listing(srv, DATE)) == before


@pytest.mark.parametrize("start,end", [
    ("12:30", "13:30"),  # 앞쪽 일부 겹침
    ("13:30", "14:30"),  # 뒤쪽 일부 겹침
    ("12:00", "15:00"),  # 감싸기 (3시간이라 R4 도 걸리므로 아래 별도)
    ("13:00", "13:30"),  # 안쪽 포함
])
def test_overlap_variants_rejected(srv, start, end):
    date = "2030-03-04"
    # 기준 예약 A 13:00~14:00 (한 번만)
    if not listing(srv, date):
        assert post(srv, date=date)[0] == 201
    st, _ = post(srv, date=date, start=start, end=end)
    assert st in (400, 409)
    assert len(listing(srv, date)) == 1


def test_contained_inside_existing_409(srv):
    date = "2030-03-05"
    assert post(srv, date=date, start="13:00", end="15:00")[0] == 201
    st, _ = post(srv, date=date, start="13:30", end="14:00")
    assert st == 409
    st, _ = post(srv, date=date, start="12:30", end="15:30")  # 감싸기, 3시간 → 400 이거나 409
    assert st in (400, 409)


def test_adjacent_after_is_allowed_201(srv):
    date = "2030-03-06"
    assert post(srv, date=date, start="10:00", end="10:30")[0] == 201
    assert post(srv, date=date, start="10:30", end="11:00")[0] == 201


def test_adjacent_before_is_allowed_201(srv):
    date = "2030-03-07"
    assert post(srv, date=date, start="10:30", end="11:00")[0] == 201
    assert post(srv, date=date, start="10:00", end="10:30")[0] == 201


def test_adjacent_to_seed_allowed(srv):
    # 시드 A 10:00~11:00 바로 뒤 · 14:00~14:30 바로 앞
    date = DATE
    st1, d1 = post(srv, date=date, start="11:00", end="11:30", user="최유나")
    st2, d2 = post(srv, date=date, start="13:30", end="14:00", user="최유나")
    assert st1 == 201 and st2 == 201
    # 정리: 다른 테스트(UI)가 시드 날짜를 읽으므로 되돌린다
    for d in (d1, d2):
        assert http("DELETE", delurl(srv, d["res_id"], "최유나"))[0] == 204


def test_other_room_same_time_independent_R7(srv):
    date = "2030-03-08"
    assert post(srv, room="A", date=date, start="10:00", end="11:00")[0] == 201
    assert post(srv, room="B", date=date, start="10:00", end="11:00")[0] == 201
    assert post(srv, room="C", date=date, start="10:00", end="11:00")[0] == 201


def test_other_date_same_time_independent(srv):
    assert post(srv, date="2030-03-09", start="10:00", end="11:00")[0] == 201
    assert post(srv, date="2030-03-10", start="10:00", end="11:00")[0] == 201


@pytest.mark.parametrize("start,end", [
    ("10:15", "11:00"),
    ("10:00", "10:45"),
    ("10:10", "10:40"),
])
def test_R1_not_30min_unit_400(srv, start, end):
    st, data = post(srv, date="2030-03-11", start=start, end=end)
    assert st == 400
    assert data["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv, "2030-03-11") == []


@pytest.mark.parametrize("start,end", [
    ("17:30", "18:30"),  # 끝이 18:00 초과
    ("08:30", "09:30"),  # 시작이 09:00 이전
    ("08:00", "08:30"),
    ("18:00", "18:30"),
    ("11:00", "10:30"),  # end < start
    ("11:00", "11:00"),  # end == start
])
def test_R2_out_of_hours_or_inverted_400(srv, start, end):
    st, data = post(srv, date="2030-03-12", start=start, end=end)
    assert st == 400
    assert data["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv, "2030-03-12") == []


def test_R2_boundaries_allowed(srv):
    date = "2030-03-13"
    assert post(srv, date=date, start="09:00", end="09:30")[0] == 201
    assert post(srv, date=date, start="17:30", end="18:00")[0] == 201


def test_R4_two_hours_ok(srv):
    assert post(srv, date="2030-03-14", start="09:00", end="11:00")[0] == 201


def test_R4_over_two_hours_400(srv):
    st, data = post(srv, date="2030-03-15", start="09:00", end="11:30")
    assert st == 400
    assert data["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert listing(srv, "2030-03-15") == []


def test_R4_three_hours_400(srv):
    st, _ = post(srv, date="2030-03-16", start="10:00", end="13:00")
    assert st == 400


@pytest.mark.parametrize("field", ["room_id", "date", "start", "end", "user"])
def test_empty_field_400(srv, field):
    b = body(date="2030-03-17")
    b[field] = ""
    st, data = http("POST", api(srv, "/api/reservations"), b)
    assert st in (400, 422)
    assert listing(srv, "2030-03-17") == []


def test_missing_body_fields_rejected(srv):
    st, _ = http("POST", api(srv, "/api/reservations"), {"room_id": "A"})
    assert st in (400, 422)


# ---------------------------------------------------------------- API: 취소 (F3, R5)

def test_delete_other_users_reservation_403(srv):
    date = "2030-04-01"
    _, r = post(srv, date=date, user="김민수")
    st, data = http("DELETE", delurl(srv, r["res_id"], "박지연"))
    assert st == 403
    assert data["detail"] == "본인 예약만 취소할 수 있습니다"
    assert [x["res_id"] for x in listing(srv, date)] == [r["res_id"]]


def test_delete_without_user_is_not_allowed(srv):
    date = "2030-04-02"
    _, r = post(srv, date=date, user="김민수")
    st, _ = http("DELETE", api(srv, "/api/reservations/%d" % r["res_id"]))
    assert st in (400, 403, 422)
    assert len(listing(srv, date)) == 1


def test_delete_own_reservation_204_and_gone(srv):
    date = "2030-04-03"
    _, r = post(srv, date=date, user="김민수")
    st, _ = http("DELETE", delurl(srv, r["res_id"], "김민수"))
    assert st == 204
    assert listing(srv, date) == []


def test_delete_missing_404(srv):
    st, _ = http("DELETE", delurl(srv, 999999, "김민수"))
    assert st == 404


def test_delete_twice_second_404(srv):
    _, r = post(srv, date="2030-04-04", user="김민수")
    url = delurl(srv, r["res_id"], "김민수")
    assert http("DELETE", url)[0] == 204
    assert http("DELETE", url)[0] == 404


def test_slot_reusable_after_cancel(srv):
    date = "2030-04-05"
    _, r = post(srv, date=date, user="김민수")
    assert post(srv, date=date, user="박지연")[0] == 409
    assert http("DELETE", delurl(srv, r["res_id"], "김민수"))[0] == 204
    assert post(srv, date=date, user="박지연")[0] == 201


def test_delete_seed_reservation_by_other_403(srv):
    st, _ = http("DELETE", delurl(srv, 1, "박지연"))  # 1 = 김민수의 A 10:00
    assert st == 403
    assert any(r["res_id"] == 1 for r in listing(srv, DATE))


# ---------------------------------------------------------------- 화면 (F1, F4, F6, R5, R6)

def open_page(pw, srv, date=None, user=None):
    page = pw.new_page()
    url = srv.base + "/" + ("?date=" + date if date else "")
    page.goto(url)
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', label=user)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_page_opens_with_title(srv, pw):
    page = pw.new_page()
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("body")
    page.close()


def test_slot_count_54(srv, pw):
    page = open_page(pw, srv, DATE)
    assert page.locator('[data-testid="slot"]').count() == 3 * 18
    page.close()


def test_slot_grid_rooms_and_times(srv, pw):
    page = open_page(pw, srv, DATE)
    keys = page.eval_on_selector_all('[data-testid="slot"]',
                                     "els => els.map(e => [e.dataset.room, e.dataset.start])")
    times = ["%02d:%02d" % (m // 60, m % 60) for m in range(9 * 60, 18 * 60, 30)]
    assert sorted(map(tuple, keys)) == sorted((r, t) for r in "ABC" for t in times)
    assert "17:30" in times and "18:00" not in times
    page.close()


def test_slot_states_are_valid(srv, pw):
    page = open_page(pw, srv, DATE)
    states = set(page.eval_on_selector_all('[data-testid="slot"]', "els => els.map(e => e.dataset.state)"))
    assert states <= {"free", "booked", "mine"}
    page.close()


def test_user_select_options_match_users(srv, pw):
    page = open_page(pw, srv, DATE)
    opts = page.eval_on_selector_all('[data-testid="user-select"] option', "os => os.map(o => o.textContent.trim())")
    assert opts == USERS
    page.close()


def test_date_shown(srv, pw):
    page = open_page(pw, srv, DATE)
    assert DATE in page.inner_text('[data-testid="date"]')
    page.close()


def test_seed_booked_slots_without_mine_user(srv, pw):
    # 박지연으로 보면 김민수의 A 10:00 · 10:30 은 남의 예약
    page = open_page(pw, srv, DATE, user="박지연")
    for t in ("10:00", "10:30"):
        assert slot(page, "A", t).get_attribute("data-state") == "booked"
        assert "김민수" in slot(page, "A", t).inner_text()
    page.close()


def test_mine_for_kim_minsu(srv, pw):
    page = open_page(pw, srv, DATE, user="김민수")
    for t in ("10:00", "10:30"):
        assert slot(page, "A", t).get_attribute("data-state") == "mine"
    # 김민수의 B 13:00~15:00 = 4칸
    for t in ("13:00", "13:30", "14:00", "14:30"):
        assert slot(page, "B", t).get_attribute("data-state") == "mine"
    page.close()


def test_free_and_range_end_exclusive(srv, pw):
    page = open_page(pw, srv, DATE, user="김민수")
    assert slot(page, "A", "09:00").get_attribute("data-state") == "free"
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"  # 끝 시각 칸은 비어 있음
    assert slot(page, "C", "15:30").get_attribute("data-state") == "free"
    assert slot(page, "C", "16:00").get_attribute("data-state") == "booked"
    assert slot(page, "C", "17:30").get_attribute("data-state") == "booked"
    page.close()


def test_seed_slot_counts_per_state(srv, pw):
    """시드 예약 칸 수: 2+1+1+4+4 = 12. 김민수 시점에서 mine 6 · booked 6 · free 42."""
    page = open_page(pw, srv, DATE, user="김민수")
    states = page.eval_on_selector_all('[data-testid="slot"]', "els => els.map(e => e.dataset.state)")
    assert states.count("mine") == 6
    assert states.count("booked") == 6
    assert states.count("free") == 42
    page.close()


def test_switching_user_changes_mine(srv, pw):
    page = open_page(pw, srv, DATE, user="김민수")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    page.select_option('[data-testid="user-select"]', label="박지연")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=A][data-start=\"10:00\"]').dataset.state === 'booked'")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.close()


def test_cancel_button_only_on_mine(srv, pw):
    page = open_page(pw, srv, DATE, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "B", "13:00").locator('[data-testid="cancel-btn"]').count() >= 1
    # 남의 booked 칸 · free 칸에는 없다
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "C", "16:00").locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_cancel_buttons_total_match_mine_slots(srv, pw):
    page = open_page(pw, srv, DATE, user="김민수")
    mine = page.locator('[data-testid="slot"][data-state="mine"]').count()
    inside_mine = page.locator('[data-testid="slot"][data-state="mine"] [data-testid="cancel-btn"]').count()
    all_btns = page.locator('[data-testid="cancel-btn"]').count()
    assert mine > 0 and inside_mine >= 1
    assert all_btns == inside_mine  # 남의 칸 · 빈 칸에 버튼이 새어 나오지 않는다
    page.close()


def test_no_cancel_button_for_booked_when_other_user(srv, pw):
    page = open_page(pw, srv, DATE, user="한도윤")  # 예약 없는 사용자
    assert page.locator('[data-testid="cancel-btn"]').count() == 0
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 0
    page.close()


def test_date_param_shows_other_day_empty(srv, pw):
    page = open_page(pw, srv, "2030-05-01", user="김민수")
    states = page.eval_on_selector_all('[data-testid="slot"]', "els => els.map(e => e.dataset.state)")
    assert len(states) == 54 and set(states) == {"free"}
    assert "2030-05-01" in page.inner_text('[data-testid="date"]')
    page.close()


def test_ui_shows_api_created_reservation(srv, pw):
    date = "2030-05-02"
    assert post(srv, date=date, room="C", start="12:00", end="13:00", user="이서준")[0] == 201
    page = open_page(pw, srv, date, user="김민수")
    for t in ("12:00", "12:30"):
        s = slot(page, "C", t)
        assert s.get_attribute("data-state") == "booked"
        assert "이서준" in s.inner_text()
    assert slot(page, "C", "13:00").get_attribute("data-state") == "free"
    page.close()


def test_ui_cancel_button_removes_reservation(srv, pw):
    date = "2030-05-03"
    _, r = post(srv, date=date, room="B", start="11:00", end="11:30", user="정하늘")
    page = open_page(pw, srv, date, user="정하늘")
    s = slot(page, "B", "11:00")
    assert s.get_attribute("data-state") == "mine"
    s.locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=B][data-start=\"11:00\"]').dataset.state === 'free'")
    assert all(x["res_id"] != r["res_id"] for x in listing(srv, date))
    page.close()


def test_ui_free_slot_has_no_user_name(srv, pw):
    page = open_page(pw, srv, DATE, user="김민수")
    text = slot(page, "A", "09:00").inner_text()
    assert not any(u in text for u in USERS)
    page.close()


def test_message_element_exists(srv, pw):
    page = open_page(pw, srv, DATE)
    assert page.locator('[data-testid="message"]').count() == 1
    page.close()


def test_ui_error_state_when_api_fails(srv, pw):
    page = pw.new_page()
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/?date=" + DATE)
    page.wait_for_selector("text=불러오지 못했습니다")
    assert page.get_by_role("button").count() >= 1  # 다시 시도 버튼
    page.close()
