# -*- coding: utf-8 -*-
"""PRD.md 의 완료 기준(10)과 업무 규칙(R1~R7), 기능(F1~F6)을 검증한다.

- API 테스트는 srv.base 로 http() 를 부른다.
- 화면 테스트는 PRD 4 의 data-testid / data-* 손잡이만 쓴다.
- 서버는 모듈 안에서 한 번만 뜨므로, 테스트가 만든 예약은 book 픽스처가 끝나고 지운다.
  (고정 데이터 RES 는 건드리지 않는다. 남의 예약 DELETE 403 확인만 한다.)
"""
import datetime
import re

import pytest

from conftest import DATE, RES, ROOMS, USERS, http

DATE2 = "2026-11-04"          # 고정 데이터에 예약이 없는 날
TIMES = ["%02d:%s" % (9 + i // 2, "30" if i % 2 else "00") for i in range(18)]   # 09:00 ~ 17:30
ROOM_IDS = [r[0] for r in ROOMS]

MSG_UNIT = "30분 단위로만 예약할 수 있습니다"
MSG_RANGE = "예약 가능 시간은 09:00~18:00 입니다"
MSG_OVERLAP = "이미 예약된 시간입니다"
MSG_LONG = "한 번에 최대 2시간까지 예약할 수 있습니다"
MSG_NOT_OWNER = "본인 예약만 취소할 수 있습니다"


# ───────────────────────── 도우미 ─────────────────────────

def body(room, start, end, user="김민수", date=DATE):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def listing(srv, date=DATE):
    status, data = http("GET", "%s/api/reservations?date=%s" % (srv.base, date))
    assert status == 200
    return data


@pytest.fixture
def book(srv):
    """예약을 POST 하고 (상태, 응답) 을 돌려준다. 만들어진 예약은 테스트가 끝나면 지운다."""
    made = []

    def _book(room, start, end, user="김민수", date=DATE):
        status, data = http("POST", srv.base + "/api/reservations", body(room, start, end, user, date))
        if status == 201 and isinstance(data, dict) and "res_id" in data:
            made.append((data["res_id"], user))
        return status, data

    yield _book
    for rid, user in made:
        http("DELETE", "%s/api/reservations/%s?user=%s" % (srv.base, rid, user))


def detail(data):
    assert isinstance(data, dict), "응답이 {'detail': ...} 형태가 아님: %r" % (data,)
    return data.get("detail")


def expected_state(room, start, user):
    for _id, r, _d, s, e, u in RES:
        if r == room and s <= start < e:
            return "mine" if u == user else "booked"
    return "free"


# ───────────────────────── F5 · API 읽기 ─────────────────────────

def test_rooms_api(srv):
    status, data = http("GET", srv.base + "/api/rooms")
    assert status == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_reservations_api_returns_seed_for_date(srv):
    data = listing(srv)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_reservations_api_filters_by_date(srv):
    assert listing(srv, DATE2) == []


# ───────────────────────── F2 · 예약 만들기 ─────────────────────────

def test_post_valid_reservation_returns_201_and_is_listed(srv, book):
    status, data = book("A", "11:00", "12:00", "박지연")
    assert status == 201
    assert data["room_id"] == "A" and data["date"] == DATE
    assert data["start"] == "11:00" and data["end"] == "12:00" and data["user"] == "박지연"
    assert isinstance(data["res_id"], int)
    assert any(r["res_id"] == data["res_id"] for r in listing(srv))


def test_post_on_other_date_does_not_appear_on_seed_date(srv, book):
    status, data = book("A", "11:00", "12:00", date=DATE2)
    assert status == 201
    assert all(r["res_id"] != data["res_id"] for r in listing(srv, DATE))
    assert any(r["res_id"] == data["res_id"] for r in listing(srv, DATE2))


@pytest.mark.parametrize("field", ["user", "room_id", "start", "end", "date"])
def test_post_blank_value_is_400(srv, field):
    payload = body("A", "11:00", "12:00", date=DATE2)
    payload[field] = ""
    before = len(listing(srv, DATE2))
    status, data = http("POST", srv.base + "/api/reservations", payload)
    assert status == 400, "빈 %s 는 400 이어야 함 (실제 %s)" % (field, status)
    assert len(listing(srv, DATE2)) == before


# ───────────────────────── R1 · 30분 단위 ─────────────────────────

@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("10:10", "10:40"), ("13:59", "14:30")])
def test_r1_non_30_minute_unit_is_400(srv, start, end):
    before = len(listing(srv, DATE2))
    status, data = http("POST", srv.base + "/api/reservations", body("A", start, end, date=DATE2))
    assert status == 400
    assert detail(data) == MSG_UNIT
    assert len(listing(srv, DATE2)) == before


# ───────────────────────── R2 · 09:00~18:00 안 ─────────────────────────

@pytest.mark.parametrize("start,end", [
    ("17:30", "18:30"),   # 끝이 18:00 을 넘음
    ("08:30", "09:30"),   # 시작이 09:00 전
    ("18:00", "18:30"),   # 전부 영업 시간 밖
    ("11:00", "11:00"),   # 길이 0
    ("11:30", "11:00"),   # 끝이 시작보다 앞
])
def test_r2_outside_hours_or_non_positive_range_is_400(srv, start, end):
    before = len(listing(srv, DATE2))
    status, data = http("POST", srv.base + "/api/reservations", body("A", start, end, date=DATE2))
    assert status == 400
    assert detail(data) == MSG_RANGE
    assert len(listing(srv, DATE2)) == before


@pytest.mark.parametrize("start,end", [("09:00", "09:30"), ("17:30", "18:00"), ("16:00", "18:00")])
def test_r2_boundaries_are_allowed(book, start, end):
    status, data = book("A", start, end, date=DATE2)
    assert status == 201, data


# ───────────────────────── R3 · 겹침 / T4 · T5 ─────────────────────────

@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 똑같이
    ("10:30", "11:30"),   # 뒤쪽이 걸침
    ("09:30", "10:30"),   # 앞쪽이 걸침
    ("10:30", "11:00"),   # 안에 쏙
    ("09:30", "11:30"),   # 통째로 감쌈
    ("10:00", "10:30"),   # 앞 절반
])
def test_r3_overlap_with_seed_is_409(srv, start, end):
    before = listing(srv)
    status, data = http("POST", srv.base + "/api/reservations", body("A", start, end, "박지연"))
    assert status == 409
    assert detail(data) == MSG_OVERLAP
    assert len(listing(srv)) == len(before)


def test_r3_overlap_by_same_user_is_still_409(srv):
    # A 10:00~11:00 은 김민수의 예약 — 본인도 겹치면 거부
    status, data = http("POST", srv.base + "/api/reservations", body("A", "10:30", "11:30", "김민수"))
    assert status == 409
    assert detail(data) == MSG_OVERLAP


def test_r3_overlap_with_newly_created_reservation(srv, book):
    assert book("C", "12:00", "13:00", "한도윤")[0] == 201
    before = len(listing(srv))
    status, data = http("POST", srv.base + "/api/reservations", body("C", "12:30", "13:30", "정하늘"))
    assert status == 409
    assert detail(data) == MSG_OVERLAP
    assert len(listing(srv)) == before


def test_r3_back_to_back_after_and_before_seed_is_201(book):
    # 기존 A 10:00~11:00 : 앞에 붙이기 · 뒤에 붙이기 모두 가능
    assert book("A", "09:30", "10:00", "박지연")[0] == 201
    assert book("A", "11:00", "11:30", "박지연")[0] == 201


def test_r3_back_to_back_chain_of_new_reservations(book):
    # 10:00~10:30 과 10:30~11:00 은 둘 다 가능
    assert book("C", "10:00", "10:30", "한도윤")[0] == 201
    assert book("C", "10:30", "11:00", "한도윤")[0] == 201
    assert book("C", "11:00", "11:30", "정하늘")[0] == 201


def test_r3_back_to_back_with_seed_in_room_b(book):
    # B 10:00~10:30(이서준) 바로 뒤 10:30~11:00
    status, _ = book("B", "10:30", "11:00", "박지연")
    assert status == 201


def test_r3_same_slot_on_other_date_is_free(book):
    assert book("A", "10:00", "11:00", "박지연", date=DATE2)[0] == 201


# ───────────────────────── R7 · 방이 다르면 무관 ─────────────────────────

def test_r7_other_room_same_time_is_not_blocked(book):
    # A 10:00 · B 10:00 은 이미 예약됨, C 10:00 은 비어 있음
    status, _ = book("C", "10:00", "11:00", "박지연")
    assert status == 201


def test_r7_same_time_in_all_rooms_on_free_date(book):
    for room in ROOM_IDS:
        assert book(room, "13:00", "14:00", "한도윤", date=DATE2)[0] == 201


# ───────────────────────── R4 · 최대 2시간 / T7 ─────────────────────────

@pytest.mark.parametrize("start,end", [("09:00", "11:30"), ("14:00", "17:00"), ("09:00", "18:00"), ("15:30", "18:00")])
def test_r4_longer_than_two_hours_is_400(srv, start, end):
    before = len(listing(srv, DATE2))
    status, data = http("POST", srv.base + "/api/reservations", body("A", start, end, date=DATE2))
    assert status == 400
    assert detail(data) == MSG_LONG
    assert len(listing(srv, DATE2)) == before


@pytest.mark.parametrize("start,end", [("09:00", "11:00"), ("14:30", "16:30"), ("16:00", "17:30"), ("12:00", "12:30")])
def test_r4_up_to_two_hours_is_201(book, start, end):
    status, data = book("A", start, end, date=DATE2)
    assert status == 201, data


# ───────────────────────── R5 · 취소는 본인만 / T8 ─────────────────────────

def test_r5_delete_by_other_user_is_403_and_reservation_stays(srv):
    status, data = http("DELETE", "%s/api/reservations/1?user=박지연" % srv.base)
    assert status == 403
    assert detail(data) == MSG_NOT_OWNER
    assert any(r["res_id"] == 1 for r in listing(srv))


def test_r5_delete_by_other_user_on_new_reservation(srv, book):
    _, made = book("C", "09:00", "10:00", "박지연")
    status, data = http("DELETE", "%s/api/reservations/%s?user=김민수" % (srv.base, made["res_id"]))
    assert status == 403
    assert detail(data) == MSG_NOT_OWNER
    assert any(r["res_id"] == made["res_id"] for r in listing(srv))


def test_r5_delete_by_owner_is_204_and_reservation_disappears(srv, book):
    _, made = book("C", "09:00", "10:00", "박지연")
    status, data = http("DELETE", "%s/api/reservations/%s?user=박지연" % (srv.base, made["res_id"]))
    assert status == 204
    assert not data
    assert all(r["res_id"] != made["res_id"] for r in listing(srv))


def test_delete_frees_the_slot_for_rebooking(srv, book):
    _, made = book("C", "09:00", "10:00", "박지연")
    assert http("DELETE", "%s/api/reservations/%s?user=박지연" % (srv.base, made["res_id"]))[0] == 204
    assert book("C", "09:00", "10:00", "한도윤")[0] == 201


def test_delete_missing_reservation_is_404(srv):
    status, _ = http("DELETE", "%s/api/reservations/99999?user=김민수" % srv.base)
    assert status == 404


def test_delete_same_reservation_twice_second_is_404(srv, book):
    _, made = book("C", "09:00", "10:00", "박지연")
    url = "%s/api/reservations/%s?user=박지연" % (srv.base, made["res_id"])
    assert http("DELETE", url)[0] == 204
    assert http("DELETE", url)[0] == 404


# ───────────────────────── 화면 도우미 ─────────────────────────

@pytest.fixture
def page(pw):
    p = pw.new_page()
    p.on("dialog", lambda d: d.accept())      # 취소 확인창이 있다면 수락
    yield p
    p.close()


def slot_loc(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def open_page(page, srv, user=None, date=DATE):
    page.goto("%s/?date=%s" % (srv.base, date))
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        select_user(page, user)


def select_user(page, user):
    page.select_option('[data-testid="user-select"]', label=user)


def read_matrix(page):
    return page.eval_on_selector_all(
        '[data-testid="slot"]',
        """els => els.map(e => ({room: e.dataset.room, start: e.dataset.start, state: e.dataset.state,
                                  text: e.innerText, cancel: e.querySelectorAll('[data-testid="cancel-btn"]').length}))""")


def wait_states(page, user, date=DATE, timeout=5000):
    """화면 상태가 user 기준 기대값과 같아질 때까지 기다리고 칸 목록을 돌려준다."""
    want = {(r, t): expected_state(r, t, user) if date == DATE else "free" for r in ROOM_IDS for t in TIMES}
    got = {}
    waited = 0
    while waited <= timeout:
        cells = read_matrix(page)
        got = {(c["room"], c["start"]): c["state"] for c in cells}
        if got == want:
            return cells
        page.wait_for_timeout(100)
        waited += 100
    diff = sorted(k for k in want if got.get(k) != want[k])[:8]
    raise AssertionError("칸 상태가 기대와 다름 (user=%s): %s" % (user, [(k, got.get(k), want[k]) for k in diff]))


def ui_book(page, room, start, minutes):
    """빈 칸을 눌러 예약 폼을 열고 minutes 분짜리로 제출한다. (폼 손잡이는 PRD 에 없어 일반 요소로 집는다.)"""
    slot_loc(page, room, start).click()
    end_select = page.locator('select:not([data-testid="user-select"])').first
    end_select.wait_for(timeout=3000)
    texts = end_select.locator("option").all_inner_texts()
    idx = next(i for i, t in enumerate(texts) if "%d분" % minutes in t)
    end_select.select_option(index=idx)
    page.get_by_role("button", name=re.compile("예약")).first.click()


# ───────────────────────── T1 · T2 · F1 · F4 화면 ─────────────────────────

def test_t1_root_opens_with_200_and_shows_title(srv, page):
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.inner_text("body")
    assert "다온소프트 회의실 예약" in page.inner_text("body")


def test_t2_grid_has_54_slots(srv, page):
    open_page(page, srv, date=DATE)
    assert page.locator('[data-testid="slot"]').count() == 3 * 18


def test_grid_is_every_room_by_every_half_hour(srv, page):
    open_page(page, srv, date=DATE)
    cells = read_matrix(page)
    assert [(c["room"], c["start"]) for c in cells] == [(r, t) for r in ROOM_IDS for t in TIMES]


def test_state_attribute_is_one_of_three_values(srv, page):
    open_page(page, srv, "김민수")
    assert {c["state"] for c in read_matrix(page)} <= {"free", "booked", "mine"}


def test_user_select_options_are_seed_users(srv, page):
    open_page(page, srv)
    names = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [n.strip() for n in names] == USERS


def test_date_shown_follows_query_param(srv, page):
    open_page(page, srv, date=DATE)
    assert DATE in page.inner_text('[data-testid="date"]')
    open_page(page, srv, date=DATE2)
    assert DATE2 in page.inner_text('[data-testid="date"]')


def test_date_defaults_to_today(srv, page):
    page.goto(srv.base + "/")
    page.wait_for_selector('[data-testid="slot"]')
    assert datetime.date.today().isoformat() in page.inner_text('[data-testid="date"]')
    assert page.locator('[data-testid="slot"]').count() == 54


def test_other_date_shows_all_free(srv, page):
    open_page(page, srv, "김민수", date=DATE2)
    wait_states(page, "김민수", date=DATE2)


# ───────────────────────── T3 · R6 · 상태 3개 ─────────────────────────

def test_t3_seed_reservations_show_as_booked_for_other_user(srv, page):
    open_page(page, srv, "박지연")
    assert slot_loc(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot_loc(page, "A", "10:30").get_attribute("data-state") == "booked"


def test_t3_same_slots_are_mine_for_owner(srv, page):
    open_page(page, srv, "김민수")
    assert slot_loc(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot_loc(page, "A", "10:30").get_attribute("data-state") == "mine"


@pytest.mark.parametrize("user", USERS)
def test_r6_every_slot_state_matches_data_for_each_user(srv, page, user):
    open_page(page, srv, user)
    wait_states(page, user)


def test_r6_changing_user_changes_mine(srv, page):
    open_page(page, srv, "김민수")
    wait_states(page, "김민수")
    select_user(page, "박지연")
    wait_states(page, "박지연")
    select_user(page, "한도윤")          # 예약이 하나도 없는 사람
    cells = wait_states(page, "한도윤")
    assert not [c for c in cells if c["state"] == "mine"]
    select_user(page, "김민수")
    wait_states(page, "김민수")


def test_booked_and_mine_slots_show_the_reserver_name(srv, page):
    open_page(page, srv, "김민수")
    wait_states(page, "김민수")
    owner = {(room, t): u for _i, room, _d, s, e, u in RES for t in TIMES if s <= t < e}
    for c in read_matrix(page):
        if c["state"] in ("booked", "mine"):
            assert owner[(c["room"], c["start"])] in c["text"], c
        else:
            assert not any(u in c["text"] for u in USERS), c


# ───────────────────────── T9 · R5 화면 · F3 ─────────────────────────

def test_t9_mine_slots_have_cancel_button_and_booked_do_not(srv, page):
    open_page(page, srv, "김민수")
    cells = wait_states(page, "김민수")
    mine = [c for c in cells if c["state"] == "mine"]
    assert len(mine) == 6                                   # A 10:00~11:00 (2칸) + B 13:00~15:00 (4칸)
    assert all(c["cancel"] >= 1 for c in mine)
    assert all(c["cancel"] == 0 for c in cells if c["state"] == "booked")
    assert all(c["cancel"] == 0 for c in cells if c["state"] == "free")
    assert slot_loc(page, "A", "10:00").get_by_test_id("cancel-btn").count() >= 1
    assert slot_loc(page, "A", "14:00").get_by_test_id("cancel-btn").count() == 0   # 박지연의 예약


def test_t9_cancel_buttons_follow_selected_user(srv, page):
    open_page(page, srv, "박지연")
    cells = wait_states(page, "박지연")
    assert page.get_by_test_id("cancel-btn").count() == len([c for c in cells if c["state"] == "mine"]) == 1
    select_user(page, "한도윤")
    wait_states(page, "한도윤")
    assert page.get_by_test_id("cancel-btn").count() == 0


def test_cancel_button_removes_own_reservation(srv, page, book):
    _, made = book("C", "09:00", "10:00", "김민수")          # C 09:00, 09:30
    open_page(page, srv, "김민수")
    target = slot_loc(page, "C", "09:00")
    assert target.get_attribute("data-state") == "mine"
    target.get_by_test_id("cancel-btn").first.click()
    from playwright.sync_api import expect
    expect(target).to_have_attribute("data-state", "free")
    expect(slot_loc(page, "C", "09:30")).to_have_attribute("data-state", "free")
    assert all(r["res_id"] != made["res_id"] for r in listing(srv))


# ───────────────────────── F2 · F6 화면 예약 · 거부 사유 ─────────────────────────

def test_clicking_free_slot_books_it_as_mine(srv, page):
    from playwright.sync_api import expect
    open_page(page, srv, "박지연")
    try:
        ui_book(page, "C", "09:00", 60)
        expect(slot_loc(page, "C", "09:00")).to_have_attribute("data-state", "mine")
        expect(slot_loc(page, "C", "09:30")).to_have_attribute("data-state", "mine")
        expect(slot_loc(page, "C", "10:00")).to_have_attribute("data-state", "free")
        made = [r for r in listing(srv) if r["room_id"] == "C" and r["start"] == "09:00"]
        assert len(made) == 1 and made[0]["end"] == "10:00" and made[0]["user"] == "박지연"
    finally:
        for r in listing(srv):
            if r["res_id"] > len(RES):
                http("DELETE", "%s/api/reservations/%s?user=%s" % (srv.base, r["res_id"], r["user"]))


def test_f6_overlap_rejection_reason_is_shown_and_nothing_is_created(srv, page):
    from playwright.sync_api import expect
    before = len(listing(srv))
    open_page(page, srv, "박지연")
    ui_book(page, "A", "09:30", 120)                    # 09:30~11:30 은 A 10:00~11:00 과 겹침
    expect(page.get_by_test_id("message")).to_contain_text(MSG_OVERLAP)
    assert len(listing(srv)) == before


def test_f6_out_of_hours_rejection_reason_is_shown(srv, page):
    from playwright.sync_api import expect
    before = len(listing(srv))
    open_page(page, srv, "박지연")
    ui_book(page, "A", "17:30", 60)                     # 17:30~18:30
    expect(page.get_by_test_id("message")).to_contain_text(MSG_RANGE)
    assert len(listing(srv)) == before


# ───────────────────────── 오류 상태 ─────────────────────────

def test_api_failure_shows_error_state_with_retry_button(srv, page):
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/")
    from playwright.sync_api import expect
    expect(page.get_by_text("불러오지 못했습니다").first).to_be_visible()
    assert page.get_by_role("button").count() >= 1


def test_error_state_retry_recovers_when_api_returns(srv, page):
    from playwright.sync_api import expect
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/?date=%s" % DATE)
    expect(page.get_by_text("불러오지 못했습니다").first).to_be_visible()
    page.unroute("**/api/**")
    retry = page.get_by_role("button", name=re.compile("다시")).first
    retry.click()
    page.wait_for_selector('[data-testid="slot"]')
    assert page.locator('[data-testid="slot"]').count() == 54
