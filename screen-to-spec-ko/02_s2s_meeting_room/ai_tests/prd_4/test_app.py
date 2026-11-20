# -*- coding: utf-8 -*-
"""다온소프트 회의실 예약 — PRD 완료 기준(10절 T1~T9)과 업무 규칙(R1~R7) 검증.

서버는 모듈 안에서 한 번만 뜨므로 예약은 테스트끼리 공유된다.
그래서 예약을 만드는 테스트는 자기 날짜를 쓰거나 끝에 지운다(`made` 픽스처).
"""
import pytest

from conftest import DATE, ROOMS, USERS, RES, http

MIN, JI, SEO = "김민수", "박지연", "이서준"

MSG_UNIT = "30분 단위로만 예약할 수 있습니다"
MSG_RANGE = "예약 가능 시간은 09:00~18:00 입니다"
MSG_OVERLAP = "이미 예약된 시간입니다"
MSG_MAX = "한 번에 최대 2시간까지 예약할 수 있습니다"
MSG_OWN = "본인 예약만 취소할 수 있습니다"


# ---------------------------------------------------------------- 도우미
def body(room, date, start, end, user=MIN):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def listing(srv, date=DATE):
    st, data = http("GET", "%s/api/reservations?date=%s" % (srv.base, date))
    assert st == 200
    return data


@pytest.fixture
def made(srv):
    """테스트가 만든 예약(res_id, user)을 끝에 지운다."""
    ids = []
    yield ids
    for rid, user in ids:
        http("DELETE", "%s/api/reservations/%s?user=%s" % (srv.base, rid, user))


def book(srv, made, room, date, start, end, user=MIN):
    st, data = http("POST", srv.base + "/api/reservations", body(room, date, start, end, user))
    if st == 201:
        made.append((data["res_id"], user))
    return st, data


def open_page(pw, srv, user=None, date=None):
    page = pw.new_page()
    page.goto(srv.base + "/" + ("?date=%s" % date if date else ""))
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', user)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


# ---------------------------------------------------------------- F5 API
def test_api_rooms(srv):
    st, data = http("GET", srv.base + "/api/rooms")
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_api_reservations_by_date(srv):
    data = listing(srv)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_api_reservations_other_date_is_empty(srv):
    assert listing(srv, "2026-12-24") == []


def test_post_returns_201_and_created_reservation(srv, made):
    st, data = book(srv, made, "C", "2026-11-10", "09:00", "10:00", JI)
    assert st == 201
    assert (data["room_id"], data["date"], data["start"], data["end"], data["user"]) == \
        ("C", "2026-11-10", "09:00", "10:00", JI)
    assert isinstance(data["res_id"], int)
    assert [r["res_id"] for r in listing(srv, "2026-11-10")] == [data["res_id"]]


def test_post_empty_value_is_400(srv):
    before = len(listing(srv))
    for bad in (body("A", DATE, "", "12:00"), body("A", DATE, "12:00", "12:30", "")):
        st, data = http("POST", srv.base + "/api/reservations", bad)
        assert st == 400
        assert data.get("detail")
    assert len(listing(srv)) == before


def test_delete_missing_is_404(srv):
    st, _ = http("DELETE", "%s/api/reservations/99999?user=%s" % (srv.base, MIN))
    assert st == 404


# ---------------------------------------------------------------- R1 30분 단위 (T6)
@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("12:00", "12:45"), ("12:10", "12:40")])
def test_r1_not_30min_unit_is_400(srv, start, end):
    before = len(listing(srv))
    st, data = http("POST", srv.base + "/api/reservations", body("B", "2026-11-04", start, end))
    assert st == 400
    assert data["detail"] == MSG_UNIT
    assert len(listing(srv)) == before


def test_r1_start_1015_on_free_time_is_400(srv):
    """T6 — 10:15 시작은 400."""
    st, _ = http("POST", srv.base + "/api/reservations", body("C", DATE, "10:15", "11:00"))
    assert st == 400


# ---------------------------------------------------------------- R2 09:00~18:00 (T6)
@pytest.mark.parametrize("start,end", [
    ("17:30", "18:30"),   # T6
    ("08:30", "09:30"),   # 시작이 이름
    ("18:00", "18:30"),   # 전부 밖
    ("11:00", "10:30"),   # end < start
    ("11:00", "11:00"),   # end == start
])
def test_r2_outside_hours_or_reversed_is_400(srv, start, end):
    before = len(listing(srv, "2026-11-05"))
    st, data = http("POST", srv.base + "/api/reservations", body("A", "2026-11-05", start, end))
    assert st == 400
    assert data["detail"] == MSG_RANGE
    assert len(listing(srv, "2026-11-05")) == before


def test_r2_boundaries_are_allowed(srv, made):
    assert book(srv, made, "A", "2026-11-06", "09:00", "09:30")[0] == 201
    assert book(srv, made, "A", "2026-11-06", "17:30", "18:00")[0] == 201


# ---------------------------------------------------------------- R3 겹침 (T4, T5)
@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 똑같이
    ("10:30", "11:30"),   # 뒤쪽 걸침
    ("09:30", "10:30"),   # 앞쪽 걸침
    ("10:30", "11:00"),   # 안쪽
    ("09:30", "11:30"),   # 감쌈
])
def test_r3_overlap_is_409_and_count_unchanged(srv, start, end):
    """T4 — A 10:00~11:00(김민수)와 겹치는 예약은 409."""
    before = listing(srv)
    st, data = http("POST", srv.base + "/api/reservations", body("A", DATE, start, end, JI))
    assert st == 409
    assert data["detail"] == MSG_OVERLAP
    assert listing(srv) == before


def test_r3_adjacent_after_and_before_are_201(srv, made):
    """T5 — 끝나는 시각 = 시작 시각이면 겹침이 아니다."""
    before = len(listing(srv))
    assert book(srv, made, "A", DATE, "11:00", "11:30", JI)[0] == 201   # 10:00~11:00 바로 뒤
    assert book(srv, made, "A", DATE, "09:30", "10:00", JI)[0] == 201   # 10:00~11:00 바로 앞
    assert len(listing(srv)) == before + 2


def test_r3_fills_gap_between_two_reservations(srv, made):
    """10:00~10:30 과 10:30~11:00 은 둘 다 가능, 그다음 같은 칸은 409."""
    d = "2026-11-07"
    assert book(srv, made, "B", d, "10:00", "10:30")[0] == 201
    assert book(srv, made, "B", d, "10:30", "11:00")[0] == 201
    assert book(srv, made, "B", d, "10:00", "10:30", JI)[0] == 409


def test_r3_same_time_other_date_is_not_overlap(srv, made):
    assert book(srv, made, "A", "2026-11-04", "10:00", "11:00")[0] == 201


# ---------------------------------------------------------------- R4 최대 2시간 (T7)
def test_r4_two_hours_ok(srv, made):
    """T7 — 2시간은 201."""
    assert book(srv, made, "C", "2026-11-08", "09:00", "11:00")[0] == 201


@pytest.mark.parametrize("start,end", [("09:00", "11:30"), ("13:00", "16:00")])
def test_r4_over_two_hours_is_400(srv, start, end):
    """T7 — 2시간 30분은 400."""
    before = len(listing(srv, "2026-11-08"))
    st, data = http("POST", srv.base + "/api/reservations", body("C", "2026-11-08", start, end))
    assert st == 400
    assert data["detail"] == MSG_MAX
    assert len(listing(srv, "2026-11-08")) == before


# ---------------------------------------------------------------- R5 취소는 본인만 (T8)
def test_r5_delete_others_is_403_and_stays(srv):
    """T8 — 남의 예약 DELETE 는 403, 예약은 남는다."""
    st, data = http("DELETE", "%s/api/reservations/1?user=%s" % (srv.base, JI))
    assert st == 403
    assert data["detail"] == MSG_OWN
    assert 1 in [r["res_id"] for r in listing(srv)]


def test_r5_delete_own_is_204_and_gone(srv, made):
    """T8 — 본인은 204, 사라진다."""
    st, data = book(srv, made, "B", "2026-11-09", "15:00", "16:00", JI)
    assert st == 201
    rid = data["res_id"]
    st, _ = http("DELETE", "%s/api/reservations/%s?user=%s" % (srv.base, rid, JI))
    assert st == 204
    assert rid not in [r["res_id"] for r in listing(srv, "2026-11-09")]


def test_r5_cancelled_time_can_be_rebooked(srv, made):
    st, data = book(srv, made, "B", "2026-11-09", "11:00", "12:00", JI)
    http("DELETE", "%s/api/reservations/%s?user=%s" % (srv.base, data["res_id"], JI))
    assert book(srv, made, "B", "2026-11-09", "11:00", "12:00", MIN)[0] == 201


# ---------------------------------------------------------------- R7 회의실 독립
def test_r7_other_room_same_time_is_independent(srv, made):
    """A 10:00 예약이 있어도 다른 방의 같은 시간은 따로다."""
    assert book(srv, made, "C", DATE, "10:00", "11:00", JI)[0] == 201   # 고정 데이터 A 10:00~11:00 과 같은 시간
    d = "2026-11-12"
    assert book(srv, made, "A", d, "10:00", "11:00")[0] == 201
    assert book(srv, made, "B", d, "10:00", "11:00", JI)[0] == 201


# ---------------------------------------------------------------- T1 / F4 화면
def test_t1_page_opens_with_title(srv, pw):
    page = pw.new_page()
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("body")
    page.close()


def test_page_has_date_and_user_select_from_seed(srv, pw):
    page = open_page(pw, srv, date=DATE)
    assert DATE in page.locator('[data-testid="date"]').inner_text()
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts if o.strip()] == USERS
    page.close()


# ---------------------------------------------------------------- T2 / F1
def test_t2_grid_has_54_slots(srv, pw):
    page = open_page(pw, srv, date=DATE)
    assert page.locator('[data-testid="slot"]').count() == 3 * 18
    page.close()


def test_grid_layout_rooms_and_times(srv, pw):
    page = open_page(pw, srv, date=DATE)
    attrs = page.eval_on_selector_all(
        '[data-testid="slot"]', "els => els.map(e => [e.dataset.room, e.dataset.start, e.dataset.state])")
    times = ["%02d:%02d" % (9 + i // 2, 30 * (i % 2)) for i in range(18)]
    assert times[0] == "09:00" and times[-1] == "17:30"
    # 회의실 순서(rooms.csv) × 시간 순서, 전부 다른 칸
    expected = [(r[0], t) for r in ROOMS for t in times]
    assert [(a[0], a[1]) for a in attrs] == expected
    assert {a[2] for a in attrs} <= {"free", "booked", "mine"}
    page.close()


def test_other_date_all_free(srv, pw):
    """F4 — ?date= 로 날짜를 바꾼다. 예약 없는 날은 전부 free."""
    page = open_page(pw, srv, date="2026-12-24")
    assert "2026-12-24" in page.locator('[data-testid="date"]').inner_text()
    assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54
    page.close()


# ---------------------------------------------------------------- T3 / R6
def test_t3_seed_reservations_show_as_booked(srv, pw):
    page = open_page(pw, srv, user=JI, date=DATE)   # 박지연 시점: A 10:00 은 남의 예약
    for s in ("10:00", "10:30"):
        assert slot(page, "A", s).get_attribute("data-state") == "booked"
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"
    assert slot(page, "A", "09:30").get_attribute("data-state") == "free"
    page.close()


def test_t3_seed_reservations_show_as_mine(srv, pw):
    page = open_page(pw, srv, user=MIN, date=DATE)
    for s in ("10:00", "10:30"):
        assert slot(page, "A", s).get_attribute("data-state") == "mine"
    page.close()


def test_booked_slot_shows_reserver_name(srv, pw):
    page = open_page(pw, srv, user=MIN, date=DATE)
    assert JI in slot(page, "A", "14:00").inner_text()
    assert MIN in slot(page, "A", "10:00").inner_text()
    page.close()


def test_seed_slot_states_match_data_for_each_user(srv, pw):
    """R6 — 선택한 사용자를 바꾸면 mine 이 바뀐다. 예약이 덮는 30분 칸 수는 변하지 않는다."""
    def cells(start, end):
        h1, m1 = map(int, start.split(":"))
        h2, m2 = map(int, end.split(":"))
        return [(("%02d:%02d" % divmod(t, 60))) for t in range(h1 * 60 + m1, h2 * 60 + m2, 30)]

    page = open_page(pw, srv, date=DATE)
    for user in USERS:
        page.select_option('[data-testid="user-select"]', user)
        want = {}
        for _, room, _, s, e, who in RES:
            for c in cells(s, e):
                want[(room, c)] = "mine" if who == user else "booked"
        for room, _, _ in ROOMS:
            for h in range(9, 18):
                for m in (0, 30):
                    t = "%02d:%02d" % (h, m)
                    exp = want.get((room, t), "free")
                    assert slot(page, room, t).get_attribute("data-state") == exp, (user, room, t)
    page.close()


def test_r6_changing_user_moves_mine(srv, pw):
    page = open_page(pw, srv, user=MIN, date=DATE)
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "B", "13:00").get_attribute("data-state") == "mine"
    page.select_option('[data-testid="user-select"]', JI)
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.close()


def test_user_with_no_reservations_has_no_mine(srv, pw):
    page = open_page(pw, srv, user="한도윤", date=DATE)
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 0
    assert page.locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


# ---------------------------------------------------------------- T9 / R5 화면
def test_t9_mine_has_cancel_button_booked_has_none(srv, pw):
    page = open_page(pw, srv, user=MIN, date=DATE)
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    for room, s in (("A", "14:00"), ("B", "10:00"), ("C", "16:00")):   # 남의 예약
        assert slot(page, room, s).get_attribute("data-state") == "booked"
        assert slot(page, room, s).locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_free_slot_has_no_cancel_button(srv, pw):
    page = open_page(pw, srv, user=MIN, date=DATE)
    assert slot(page, "C", "09:00").locator('[data-testid="cancel-btn"]').count() == 0
    page.close()


def test_cancel_button_deletes_reservation(srv, pw, made):
    """화면에서 내 예약의 취소 버튼을 누르면 예약이 사라지고 칸이 free 로 돌아온다."""
    d = "2026-11-16"
    st, data = book(srv, made, "C", d, "12:00", "12:30", JI)
    assert st == 201
    page = open_page(pw, srv, user=JI, date=d)
    assert slot(page, "C", "12:00").get_attribute("data-state") == "mine"
    slot(page, "C", "12:00").locator('[data-testid="cancel-btn"]').click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=C][data-start=\"12:00\"]')"
        ".dataset.state === 'free'")
    assert listing(srv, d) == []
    page.close()


# ---------------------------------------------------------------- F2 / F6 화면 예약 · 거부 사유
def _submit_form(page, end_label):
    """PRD 는 예약 폼의 data-testid 를 정하지 않았다(끝 선택: 30 · 60 · 90 · 120분).
    그래서 폼 안의 <select> 와 버튼을 모양으로 집는다."""
    form_select =page.locator('select:visible:not([data-testid="user-select"])').first
    form_select.select_option(label=end_label)
    page.get_by_role("button", name="예약").last.click()


def test_ui_click_free_slot_books_it(srv, pw, made):
    d = "2026-11-17"
    page = open_page(pw, srv, user=JI, date=d)
    slot(page, "A", "13:00").click()
    _submit_form(page, "60분")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=A][data-start=\"13:00\"]')"
        ".dataset.state === 'mine'")
    rows = listing(srv, d)
    assert [(r["room_id"], r["start"], r["end"], r["user"]) for r in rows] == [("A", "13:00", "14:00", JI)]
    made.append((rows[0]["res_id"], JI))
    assert slot(page, "A", "13:30").get_attribute("data-state") == "mine"
    page.close()


def test_ui_rejection_detail_shown_in_message(srv, pw):
    """F6 — 서버가 거부하면 detail 문구를 그대로 보여 준다. (A 09:30 + 60분 → 10:00 예약과 겹침)"""
    page = open_page(pw, srv, user=JI, date=DATE)
    slot(page, "A", "09:30").click()
    _submit_form(page, "60분")
    page.wait_for_function(
        "t => document.querySelector('[data-testid=message]').innerText.includes(t)", arg=MSG_OVERLAP)
    assert MSG_OVERLAP in page.locator('[data-testid="message"]').inner_text()
    assert len(listing(srv)) == len(RES)
    page.close()


# ---------------------------------------------------------------- 오류 상태
def test_error_state_when_api_fails(srv, pw):
    page = pw.new_page()
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/?date=%s" % DATE)
    page.wait_for_selector("text=불러오지 못했습니다")
    assert page.get_by_role("button", name="다시").count() >= 1
    page.close()


def test_error_state_recovers_on_retry(srv, pw):
    page = pw.new_page()
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/?date=%s" % DATE)
    page.wait_for_selector("text=불러오지 못했습니다")
    page.unroute("**/api/**")
    page.get_by_role("button", name="다시").first.click()
    page.wait_for_selector('[data-testid="slot"]')
    assert page.locator('[data-testid="slot"]').count() == 54
    page.close()


# ---------------------------------------------------------------- 데이터 교체
def test_data_comes_from_seed_not_hardcoded(srv):
    """서버는 CSV 를 읽는다 — 고정 데이터와 정확히 일치해야 한다(5건, 방 3, 날짜 DATE)."""
    assert len(listing(srv)) == 5
    st, rooms = http("GET", srv.base + "/api/rooms")
    assert len(rooms) == 3
