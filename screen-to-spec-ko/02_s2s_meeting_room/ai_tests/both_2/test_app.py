# -*- coding: utf-8 -*-
"""다온소프트 회의실 예약 — PRD.md 기준 테스트 (F1~F6, R1~R7).

서버는 모듈 단위로 한 번 뜨고 예약이 유지되므로, 테스트가 만든 예약은 끝에 지워 서로 영향을 주지 않는다.
변경 테스트는 고정 데이터와 겹치지 않는 C 회의실 오전(09:00~12:00)을 쓴다.
"""
import pytest

from conftest import DATE, RES, ROOMS, USERS, http

ME = "김민수"
OTHER = "박지연"
SLOT_TIMES = ["%02d:%02d" % (m // 60, m % 60) for m in range(9 * 60, 18 * 60, 30)]


# ---------- 도우미 ----------
def body(start, end, room="C", user=ME, date=DATE):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def listing(srv, date=DATE):
    s, data = http("GET", srv.base + "/api/reservations?date=" + date)
    assert s == 200
    return data


@pytest.fixture
def book(srv):
    """예약을 만들고, 테스트가 끝나면 만든 예약을 모두 지운다."""
    made = []

    def _book(start, end, **kw):
        s, data = http("POST", srv.base + "/api/reservations", body(start, end, **kw))
        if s == 201:
            made.append((data["res_id"], data["user"]))
        return s, data

    yield _book
    for rid, user in made:
        http("DELETE", "%s/api/reservations/%d?user=%s" % (srv.base, rid, user))


# ---------- F5: 조회 API ----------
def test_rooms_api(srv):
    s, data = http("GET", srv.base + "/api/rooms")
    assert s == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_list_reservations_returns_seed_for_date(srv):
    got = listing(srv)
    assert sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in got) == sorted(RES)


def test_list_reservations_other_date_is_empty(srv):
    assert listing(srv, "2026-11-04") == []


# ---------- F2: 예약 생성 ----------
def test_create_returns_201_and_reservation(srv, book):
    s, data = book("09:00", "10:00")
    assert s == 201
    assert (data["room_id"], data["date"], data["start"], data["end"], data["user"]) == ("C", DATE, "09:00", "10:00", ME)
    assert isinstance(data["res_id"], int)
    assert data["res_id"] not in {r[0] for r in RES}
    assert data["res_id"] in [r["res_id"] for r in listing(srv)]


def test_created_ids_are_unique(srv, book):
    _, a = book("09:00", "09:30")
    _, b = book("09:30", "10:00")
    assert a["res_id"] != b["res_id"]


@pytest.mark.parametrize("field", ["room_id", "date", "start", "end", "user"])
def test_empty_value_is_400(srv, field):
    b = body("09:00", "10:00")
    b[field] = ""
    before = listing(srv)
    s, data = http("POST", srv.base + "/api/reservations", b)
    assert s == 400
    assert listing(srv) == before


# ---------- R1: 30분 단위 ----------
@pytest.mark.parametrize("start,end", [("09:15", "10:00"), ("10:15", "11:00"), ("09:00", "10:10"), ("09:00", "09:45")])
def test_r1_not_30min_unit_is_400(srv, start, end):
    before = listing(srv)
    s, data = http("POST", srv.base + "/api/reservations", body(start, end))
    assert s == 400
    assert data["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert listing(srv) == before


# ---------- R2: 09:00~18:00 ----------
@pytest.mark.parametrize("start,end", [("17:30", "18:30"), ("08:30", "09:30"), ("08:00", "09:00"), ("18:00", "18:30")])
def test_r2_outside_hours_is_400(srv, start, end):
    before = listing(srv)
    s, data = http("POST", srv.base + "/api/reservations", body(start, end))
    assert s == 400
    assert data["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv) == before


@pytest.mark.parametrize("start,end", [("10:00", "10:00"), ("11:00", "10:00")])
def test_r2_end_not_after_start_is_400(srv, start, end):
    before = listing(srv)
    s, data = http("POST", srv.base + "/api/reservations", body(start, end))
    assert s == 400
    assert data["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert listing(srv) == before


def test_r2_boundaries_are_allowed(srv, book):
    s1, _ = book("09:00", "09:30")      # 처음 칸
    s2, _ = book("17:30", "18:00", room="B", date="2026-11-05")   # 마지막 칸
    assert (s1, s2) == (201, 201)


# ---------- R3: 겹침 ----------
@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 똑같이
    ("10:30", "11:30"),   # 뒤쪽이 겹침
    ("09:30", "10:30"),   # 앞쪽이 겹침
])
def test_r3_overlap_is_409(srv, start, end):
    before = listing(srv)
    s, data = http("POST", srv.base + "/api/reservations", body(start, end, room="A", user=OTHER))
    assert s == 409
    assert data["detail"] == "이미 예약된 시간입니다"
    assert listing(srv) == before


def test_r3_contained_and_containing_are_409(srv, book):
    assert book("10:00", "12:00")[0] == 201
    assert book("10:30", "11:00")[0] == 409      # 안에 쏙 들어감
    assert book("09:30", "12:30")[0] == 409      # 감싸 버림


def test_r3_overlap_with_just_created_reservation(srv, book):
    assert book("11:00", "12:00")[0] == 201
    s, data = book("11:30", "12:30")
    assert s == 409 and data["detail"] == "이미 예약된 시간입니다"


def test_r3_back_to_back_is_allowed(srv, book):
    """끝나는 시각 = 시작 시각이면 겹침이 아니다 (기존 A 10:00~11:00 의 앞뒤)."""
    assert book("09:30", "10:00", room="A")[0] == 201
    assert book("11:00", "11:30", room="A")[0] == 201
    assert book("10:00", "10:30")[0] == 201
    assert book("10:30", "11:00")[0] == 201


# ---------- R7: 회의실 · 날짜 무관 ----------
def test_r7_other_room_same_time_is_independent(srv, book):
    # A 10:00~11:00 은 이미 있음 → C 에 같은 시간은 가능
    assert book("10:00", "11:00", room="C")[0] == 201


def test_r7_other_date_same_time_is_independent(srv, book):
    assert book("10:00", "11:00", room="A", date="2026-11-04")[0] == 201


# ---------- R4: 최대 2시간 ----------
def test_r4_over_2h_is_400(srv):
    before = listing(srv)
    s, data = http("POST", srv.base + "/api/reservations", body("09:00", "11:30"))
    assert s == 400
    assert data["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert listing(srv) == before


def test_r4_2h30_is_400_on_free_room(srv):
    s, data = http("POST", srv.base + "/api/reservations", body("09:30", "12:00", room="B", date="2026-11-04"))
    assert s == 400
    assert data["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"


def test_r4_exactly_2h_is_201(srv, book):
    s, data = book("09:00", "11:00")
    assert s == 201 and (data["start"], data["end"]) == ("09:00", "11:00")


# ---------- F3 / R5: 취소 ----------
def test_delete_by_other_user_is_403(srv, book):
    _, made = book("09:00", "10:00")
    url = "%s/api/reservations/%d?user=%s" % (srv.base, made["res_id"], OTHER)
    s, data = http("DELETE", url)
    assert s == 403
    assert data["detail"] == "본인 예약만 취소할 수 있습니다"
    assert made["res_id"] in [r["res_id"] for r in listing(srv)]


def test_delete_without_user_is_403(srv, book):
    _, made = book("09:00", "10:00")
    s, _ = http("DELETE", "%s/api/reservations/%d" % (srv.base, made["res_id"]))
    assert s == 403
    assert made["res_id"] in [r["res_id"] for r in listing(srv)]


def test_delete_own_is_204_and_gone(srv, book):
    _, made = book("09:00", "10:00")
    s, _ = http("DELETE", "%s/api/reservations/%d?user=%s" % (srv.base, made["res_id"], ME))
    assert s == 204
    assert made["res_id"] not in [r["res_id"] for r in listing(srv)]


def test_delete_frees_the_slot(srv, book):
    _, made = book("09:00", "10:00")
    http("DELETE", "%s/api/reservations/%d?user=%s" % (srv.base, made["res_id"], ME))
    assert book("09:00", "10:00")[0] == 201


def test_delete_unknown_id_is_404(srv):
    s, _ = http("DELETE", "%s/api/reservations/99999?user=%s" % (srv.base, ME))
    assert s == 404


def test_delete_seed_reservation_by_other_is_403(srv):
    s, _ = http("DELETE", "%s/api/reservations/1?user=%s" % (srv.base, OTHER))   # res 1 = 김민수의 A 10:00
    assert s == 403
    assert 1 in [r["res_id"] for r in listing(srv)]


# ---------- 화면 (F1, F4, F6, R5, R6) ----------
@pytest.fixture
def page(pw, srv):
    p = pw.new_page()
    yield p
    p.close()


def open_page(page, srv, user=None, date=None):
    page.goto(srv.base + "/" + ("?date=" + date if date else ""))
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', label=user)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_page_opens_with_title(srv, page):
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("h1")


def test_page_has_54_slots(srv, page):
    open_page(page, srv)
    assert page.locator('[data-testid="slot"]').count() == 3 * 18


def test_slot_layout_rooms_and_times(srv, page):
    open_page(page, srv)
    got = page.eval_on_selector_all('[data-testid="slot"]', "els => els.map(e => [e.dataset.room, e.dataset.start])")
    assert got == [[r[0], t] for r in ROOMS for t in SLOT_TIMES]


def test_slot_states_are_only_the_three(srv, page):
    open_page(page, srv, ME)
    states = set(page.eval_on_selector_all('[data-testid="slot"]', "els => els.map(e => e.dataset.state)"))
    assert states <= {"free", "booked", "mine"}
    assert states == {"free", "booked", "mine"}


def test_date_is_shown(srv, page):
    open_page(page, srv)
    assert DATE in page.inner_text('[data-testid="date"]')


def test_user_select_options_are_users(srv, page):
    open_page(page, srv)
    opts = page.eval_on_selector_all('[data-testid="user-select"] option', "els => els.map(e => e.textContent.trim())")
    assert opts == USERS


def test_seed_reservations_show_as_booked_for_others(srv, page):
    open_page(page, srv, "최유나")
    for room, start in [("A", "10:00"), ("A", "10:30"), ("B", "10:00"), ("B", "13:00"), ("B", "14:30")]:
        assert slot(page, room, start).get_attribute("data-state") == "booked", (room, start)
    assert "김민수" in slot(page, "A", "10:00").inner_text()


def test_end_time_slot_is_free(srv, page):
    """A 10:00~11:00 예약의 11:00 칸, B 10:00~10:30 의 10:30 칸은 비어 있다."""
    open_page(page, srv, ME)
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"
    assert slot(page, "B", "10:30").get_attribute("data-state") == "free"
    assert slot(page, "A", "09:30").get_attribute("data-state") == "free"


def test_r6_mine_follows_selected_user(srv, page):
    open_page(page, srv, ME)
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:30").get_attribute("data-state") == "mine"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.select_option('[data-testid="user-select"]', label="박지연")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=A][data-start=\"14:00\"]').dataset.state === 'mine'")
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "09:00").get_attribute("data-state") == "free"


def test_mine_slot_has_cancel_button_and_booked_has_none(srv, page):
    open_page(page, srv, ME)
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "B", "13:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() == 0   # 박지연
    assert slot(page, "B", "10:00").locator('[data-testid="cancel-btn"]').count() == 0   # 이서준
    assert slot(page, "C", "16:00").locator('[data-testid="cancel-btn"]').count() == 0   # 최유나
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0   # 빈 칸


def test_cancel_buttons_only_on_own_slots(srv, page):
    open_page(page, srv, ME)
    owners = page.eval_on_selector_all(
        '[data-testid="cancel-btn"]', "els => els.map(e => e.closest('[data-testid=slot]').dataset.state)")
    assert owners and set(owners) == {"mine"}


def test_cancel_button_removes_reservation(srv, page, book):
    _, made = book("09:00", "09:30")
    open_page(page, srv, ME)
    s = slot(page, "C", "09:00")
    assert s.get_attribute("data-state") == "mine"
    s.locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=C][data-start=\"09:00\"]').dataset.state === 'free'")
    assert made["res_id"] not in [r["res_id"] for r in listing(srv)]


def test_date_query_shows_other_day_empty(srv, page):
    open_page(page, srv, ME, date="2026-11-04")
    assert "2026-11-04" in page.inner_text('[data-testid="date"]')
    states = set(page.eval_on_selector_all('[data-testid="slot"]', "els => els.map(e => e.dataset.state)"))
    assert states == {"free"}


def test_page_reflects_new_reservation(srv, page, book):
    book("09:00", "10:00", user=OTHER)
    open_page(page, srv, ME)
    assert slot(page, "C", "09:00").get_attribute("data-state") == "booked"
    assert slot(page, "C", "09:30").get_attribute("data-state") == "booked"
    assert slot(page, "C", "10:00").get_attribute("data-state") == "free"


def test_f6_rejection_reason_shown_in_message(srv, page):
    """빈 칸(A 09:30)을 눌러 60분으로 예약 → A 10:00 과 겹쳐 거부, 서버 detail 이 메시지 줄에 보인다."""
    n_before = len(listing(srv))
    open_page(page, srv, "최유나")
    slot(page, "A", "09:30").click()
    page.locator("select:not([data-testid=user-select])").first.select_option(index=1)   # 30·60·90·120 중 60분
    page.get_by_role("button", name="예약").first.click()
    page.wait_for_function("() => document.querySelector('[data-testid=message]').textContent.trim() !== ''")
    assert "이미 예약된 시간입니다" in page.inner_text('[data-testid="message"]')
    assert len(listing(srv)) == n_before
