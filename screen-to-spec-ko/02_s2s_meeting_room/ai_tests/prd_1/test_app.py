# -*- coding: utf-8 -*-
"""PRD 완료 기준(T1~T9)과 업무 규칙(R1~R7) 검증.

- 서버 상태는 모듈 안에서 이어지므로, 예약을 만드는 테스트는 고정 데이터(DATE)가 아닌
  별도 날짜(FREE_DATE)를 쓰고 끝나면 지운다. DATE 의 고정 예약은 건드리지 않는다.
"""
import pytest

from conftest import DATE, ROOMS, USERS, RES, http

FREE_DATE = "2026-11-04"   # 고정 예약이 없는 날
MSG_UNIT = "30분 단위로만 예약할 수 있습니다"
MSG_RANGE = "예약 가능 시간은 09:00~18:00 입니다"
MSG_OVERLAP = "이미 예약된 시간입니다"
MSG_MAX = "한 번에 최대 2시간까지 예약할 수 있습니다"
MSG_OWNER = "본인 예약만 취소할 수 있습니다"

TIMES = ["%02d:%02d" % (9 + i // 2, 30 * (i % 2)) for i in range(18)]


# ---------- 도우미 ----------
def body(room="A", start="13:00", end="14:00", user="박지연", date=FREE_DATE):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def listing(srv, date=FREE_DATE):
    st, data = http("GET", "%s/api/reservations?date=%s" % (srv.base, date))
    assert st == 200
    return data


@pytest.fixture
def made(srv):
    """테스트가 만든 예약 id 를 기록했다가 끝에 지운다."""
    ids = []

    def make(**kw):
        st, r = http("POST", srv.base + "/api/reservations", body(**kw))
        assert st == 201, (st, r)
        ids.append((r["res_id"], r["user"]))
        return r

    yield make
    for rid, user in ids:
        http("DELETE", "%s/api/reservations/%s?user=%s" % (srv.base, rid, user))


def post(srv, **kw):
    return http("POST", srv.base + "/api/reservations", body(**kw))


@pytest.fixture
def page(pw):
    p = pw.new_page()
    yield p
    p.close()


def open_page(page, srv, date=None, user=None):
    page.goto(srv.base + "/" + ("?date=" + date if date else ""))
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', user)


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


# ---------- T1 ~ T2 화면 기본 ----------
def test_t1_root_opens_with_title(srv, page):
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("body")


def test_t2_grid_has_54_slots(srv, page):
    open_page(page, srv)
    assert page.locator('[data-testid="slot"]').count() == 3 * 18


def test_grid_layout_rooms_and_times(srv, page):
    """칸은 회의실 3 × 09:00~17:30 30분 18칸, 회의실 순서는 rooms.csv 순."""
    open_page(page, srv)
    attrs = page.eval_on_selector_all(
        '[data-testid="slot"]', "els => els.map(e => [e.dataset.room, e.dataset.start, e.dataset.state])")
    assert [a[0] for a in attrs][::18] == [r[0] for r in ROOMS]
    for room, _, _ in ROOMS:
        assert [a[1] for a in attrs if a[0] == room] == TIMES
    assert {a[2] for a in attrs} <= {"free", "booked", "mine"}


def test_header_date_and_user_select(srv, page):
    open_page(page, srv, date=DATE)
    assert DATE in page.inner_text('[data-testid="date"]')
    opts = page.eval_on_selector_all('[data-testid="user-select"] option', "els => els.map(e => e.textContent.trim())")
    assert [o for o in opts if o in USERS] == USERS
    assert page.locator('[data-testid="message"]').count() == 1


# ---------- T3 / R6 칸 상태 ----------
def test_t3_seed_reservations_show_as_booked(srv, page):
    open_page(page, srv, date=DATE, user="박지연")
    for start in ("10:00", "10:30"):
        s = slot(page, "A", start)
        assert s.get_attribute("data-state") == "booked"
        assert "김민수" in s.inner_text()
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"


def test_t3_selecting_owner_makes_slots_mine(srv, page):
    open_page(page, srv, date=DATE, user="김민수")
    for start in ("10:00", "10:30"):
        s = slot(page, "A", start)
        assert s.get_attribute("data-state") == "mine"
        assert "김민수" in s.inner_text()


def test_r6_switching_user_changes_mine(srv, page):
    open_page(page, srv, date=DATE, user="김민수")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    page.select_option('[data-testid="user-select"]', "박지연")
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=A][data-start=\"10:00\"]').dataset.state === 'booked'")
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"


def test_r6_all_seed_reservations_cover_exact_slots(srv, page):
    """고정 예약 5건이 해당 방 · 시간 칸만 차지한다(끝 시각 칸은 비어 있다)."""
    open_page(page, srv, date=DATE, user="김민수")
    expect = {}
    for _, room, _, st, en, user in RES:
        for t in TIMES:
            if st <= t < en:
                expect[(room, t)] = "mine" if user == "김민수" else "booked"
    for room, _, _ in ROOMS:
        for t in TIMES:
            want = expect.get((room, t), "free")
            assert slot(page, room, t).get_attribute("data-state") == want, (room, t)


def test_f4_other_date_is_all_free(srv, page):
    open_page(page, srv, date=FREE_DATE, user="김민수")
    assert FREE_DATE in page.inner_text('[data-testid="date"]')
    states = page.eval_on_selector_all('[data-testid="slot"]', "els => els.map(e => e.dataset.state)")
    assert len(states) == 54 and set(states) == {"free"}


# ---------- T9 / R5 화면의 취소 버튼 ----------
def test_t9_cancel_button_only_on_mine(srv, page):
    open_page(page, srv, date=DATE, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "B", "13:00").locator('[data-testid="cancel-btn"]').count() >= 1   # 김민수의 두 번째 예약
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "B", "10:00").locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "A", "09:00").locator('[data-testid="cancel-btn"]').count() == 0  # free
    # 화면 전체에서도 mine 칸에만 취소 버튼이 있다
    n_btn = page.locator('[data-testid="cancel-btn"]').count()
    n_mine = page.locator('[data-testid="slot"][data-state="mine"]').count()
    assert n_btn >= 1 and n_btn <= n_mine


def test_r5_no_cancel_button_for_other_user(srv, page):
    open_page(page, srv, date=DATE, user="박지연")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() >= 1


def test_f3_cancel_from_screen_frees_slot(srv, page, made):
    r = made(room="C", start="09:00", end="10:00", user="김민수")
    open_page(page, srv, date=FREE_DATE, user="김민수")
    assert slot(page, "C", "09:00").get_attribute("data-state") == "mine"
    slot(page, "C", "09:00").locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=C][data-start=\"09:00\"]').dataset.state === 'free'")
    assert all(x["res_id"] != r["res_id"] for x in listing(srv))


def test_f2_book_from_screen(srv, page):
    """빈 칸 클릭 → 폼에서 60분 선택 → 예약. (폼 요소는 PRD 에 testid 가 없어 태그 · 글자로 집는다)"""
    open_page(page, srv, date=FREE_DATE, user="박지연")
    slot(page, "B", "15:00").click()
    page.locator("select:not([data-testid='user-select'])").first.select_option(label="60분")
    page.get_by_role("button", name="예약").first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=slot][data-room=B][data-start=\"15:00\"]').dataset.state === 'mine'")
    assert slot(page, "B", "15:30").get_attribute("data-state") == "mine"
    assert slot(page, "B", "16:00").get_attribute("data-state") == "free"
    mine = [x for x in listing(srv) if x["room_id"] == "B"]
    assert [(x["start"], x["end"], x["user"]) for x in mine] == [("15:00", "16:00", "박지연")]
    for x in mine:
        http("DELETE", "%s/api/reservations/%s?user=박지연" % (srv.base, x["res_id"]))


def test_f6_server_reject_detail_shown_on_screen(srv, page):
    """겹치는 예약을 화면에서 시도하면 서버 detail 문구가 메시지 줄에 그대로 나온다."""
    open_page(page, srv, date=DATE, user="박지연")
    slot(page, "A", "09:30").click()                      # 09:30 시작, 120분 → 10:00 김민수 예약과 겹침
    page.locator("select:not([data-testid='user-select'])").first.select_option(label="120분")
    page.get_by_role("button", name="예약").first.click()
    page.wait_for_function(
        "m => document.querySelector('[data-testid=message]').textContent.includes(m)", arg=MSG_OVERLAP)
    assert len([x for x in listing(srv, DATE)]) == len(RES)


def test_error_state_when_api_fails(srv, page):
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/?date=" + DATE)
    page.wait_for_function("() => document.body.innerText.includes('불러오지 못했습니다')")
    assert page.get_by_role("button", name="다시").count() >= 1


# ---------- F5 API 조회 ----------
def test_api_rooms(srv):
    st, data = http("GET", srv.base + "/api/rooms")
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in data] == ROOMS


def test_api_reservations_seed(srv):
    data = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data)
    assert got == sorted(RES)


def test_api_reservations_filtered_by_date(srv):
    assert listing(srv, FREE_DATE) == []
    assert all(r["date"] == DATE for r in listing(srv, DATE))


# ---------- T4 / R3 겹침 ----------
def test_t4_overlap_is_409_and_count_unchanged(srv):
    before = len(listing(srv, DATE))
    st, r = http("POST", srv.base + "/api/reservations", body(room="A", start="10:30", end="11:30", user="박지연", date=DATE))
    assert st == 409
    assert r["detail"] == MSG_OVERLAP
    assert len(listing(srv, DATE)) == before


@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 완전히 같음
    ("10:00", "10:30"),   # 앞부분에 포함
    ("10:30", "11:00"),   # 뒷부분에 포함
    ("09:30", "10:30"),   # 앞에서 걸침
    ("10:30", "11:30"),   # 뒤에서 걸침
    ("09:00", "12:00"),   # 기존 예약을 감쌈
])
def test_r3_overlap_variants(srv, start, end):
    before = len(listing(srv, DATE))
    st, r = post(srv, room="A", start=start, end=end, date=DATE)
    assert st == 409 and r["detail"] == MSG_OVERLAP
    assert len(listing(srv, DATE)) == before


def test_r3_overlap_among_new_reservations(srv, made):
    made(room="B", start="09:00", end="10:00", user="이서준")
    st, r = post(srv, room="B", start="09:30", end="10:30", user="정하늘")
    assert st == 409 and r["detail"] == MSG_OVERLAP


# ---------- T5 / R3 붙여 예약 ----------
def test_t5_adjacent_reservations_allowed(srv, made):
    made(room="A", start="10:00", end="10:30")
    made(room="A", start="10:30", end="11:00", user="이서준")     # 앞 예약의 끝 = 시작
    made(room="A", start="09:30", end="10:00", user="최유나")     # 뒤 예약의 시작 = 끝
    assert len(listing(srv)) == 3


def test_t5_adjacent_to_seed_reservation(srv):
    # A 10:00~11:00 (고정) 바로 뒤 11:00~11:30, 바로 앞 09:30~10:00
    for s, e in (("11:00", "11:30"), ("09:30", "10:00")):
        st, r = post(srv, room="A", start=s, end=e, date=DATE)
        assert st == 201, (s, e, r)
        http("DELETE", "%s/api/reservations/%s?user=박지연" % (srv.base, r["res_id"]))


# ---------- R7 / 날짜 ----------
def test_r7_other_room_same_time_independent(srv, made):
    made(room="A", start="10:00", end="11:00")
    made(room="B", start="10:00", end="11:00", user="이서준")
    made(room="C", start="10:00", end="11:00", user="최유나")
    assert len(listing(srv)) == 3


def test_r3_same_room_other_date_is_not_overlap(srv, made):
    made(room="A", start="10:00", end="11:00", date=FREE_DATE)
    made(room="A", start="10:00", end="11:00", date="2026-11-05")
    assert len(listing(srv, "2026-11-05")) == 1


def test_r3_reservation_response_fields(srv, made):
    r = made(room="C", start="12:00", end="13:00", user="정하늘")
    assert isinstance(r["res_id"], int)
    assert (r["room_id"], r["date"], r["start"], r["end"], r["user"]) == ("C", FREE_DATE, "12:00", "13:00", "정하늘")
    assert r in listing(srv)


# ---------- T6 / R1 / R2 ----------
def test_t6_start_not_on_30min_is_400(srv):
    st, r = post(srv, start="10:15", end="11:00")
    assert st == 400 and r["detail"] == MSG_UNIT
    assert listing(srv) == []


@pytest.mark.parametrize("start,end", [("10:00", "10:45"), ("10:10", "10:40"), ("10:00", "10:59")])
def test_r1_non_30min_is_400(srv, start, end):
    st, r = post(srv, start=start, end=end)
    assert st == 400 and r["detail"] == MSG_UNIT
    assert listing(srv) == []


def test_t6_end_after_18_is_400(srv):
    st, r = post(srv, start="17:30", end="18:30")
    assert st == 400 and r["detail"] == MSG_RANGE
    assert listing(srv) == []


@pytest.mark.parametrize("start,end", [
    ("08:30", "09:30"),   # 시작이 09:00 전
    ("08:00", "09:00"),
    ("18:00", "18:30"),   # 전부 18:00 이후
    ("10:00", "10:00"),   # 길이 0
    ("11:00", "10:00"),   # 끝이 시작보다 앞
])
def test_r2_outside_hours_or_reversed_is_400(srv, start, end):
    st, r = post(srv, start=start, end=end)
    assert st == 400 and r["detail"] == MSG_RANGE
    assert listing(srv) == []


def test_r2_boundaries_are_allowed(srv, made):
    made(room="A", start="09:00", end="09:30")
    made(room="A", start="17:30", end="18:00", user="이서준")
    made(room="B", start="17:00", end="18:00")
    assert len(listing(srv)) == 3


def test_r1_r2_time_not_30min_and_in_range_checked_before_save(srv):
    st, _ = post(srv, start="17:45", end="18:15")
    assert st == 400
    assert listing(srv) == []


# ---------- T7 / R4 ----------
def test_t7_2h30_is_400_and_2h_is_201(srv, made):
    st, r = post(srv, start="09:00", end="11:30")
    assert st == 400 and r["detail"] == MSG_MAX
    assert listing(srv) == []
    made(room="A", start="09:00", end="11:00")
    assert len(listing(srv)) == 1


@pytest.mark.parametrize("start,end", [("09:00", "12:00"), ("10:00", "12:30"), ("13:00", "17:30")])
def test_r4_over_2h_is_400(srv, start, end):
    st, r = post(srv, start=start, end=end)
    assert st == 400 and r["detail"] == MSG_MAX
    assert listing(srv) == []


def test_r4_just_over_2h_and_just_2h(srv, made):
    st, r = post(srv, room="C", start="10:00", end="12:30")
    assert st == 400
    made(room="C", start="10:00", end="12:00")
    made(room="C", start="12:00", end="12:30", user="이서준")   # 30분도 가능


# ---------- 빈 값 / 형식 ----------
@pytest.mark.parametrize("field", ["room_id", "date", "start", "end", "user"])
def test_missing_or_empty_field_is_rejected(srv, field):
    for value in (None, ""):
        b = body()
        if value is None:
            del b[field]
        else:
            b[field] = value
        st, _ = http("POST", srv.base + "/api/reservations", b)
        assert st in (400, 422), (field, value, st)
    assert listing(srv) == []


# ---------- T8 / R5 취소 ----------
def test_t8_delete_others_is_403_and_stays(srv):
    st, r = http("DELETE", "%s/api/reservations/1?user=박지연" % srv.base)
    assert st == 403
    assert r["detail"] == MSG_OWNER
    assert any(x["res_id"] == 1 for x in listing(srv, DATE))


def test_t8_delete_own_is_204_and_gone(srv, made):
    r = made(room="A", start="12:00", end="13:00", user="김민수")
    st, _ = http("DELETE", "%s/api/reservations/%s?user=김민수" % (srv.base, r["res_id"]))
    assert st == 204
    assert all(x["res_id"] != r["res_id"] for x in listing(srv))


def test_t8_deleted_slot_can_be_booked_again(srv, made):
    r = made(room="A", start="12:00", end="13:00", user="김민수")
    http("DELETE", "%s/api/reservations/%s?user=김민수" % (srv.base, r["res_id"]))
    made(room="A", start="12:00", end="13:00", user="박지연")


def test_r5_delete_without_or_with_unknown_user_is_not_204(srv, made):
    r = made(room="B", start="12:00", end="13:00", user="김민수")
    for q in ("", "?user=", "?user=없는사람"):
        st, _ = http("DELETE", "%s/api/reservations/%s%s" % (srv.base, r["res_id"], q))
        assert st != 204 and st < 500, (q, st)
    assert any(x["res_id"] == r["res_id"] for x in listing(srv))


def test_delete_missing_is_404(srv):
    st, _ = http("DELETE", "%s/api/reservations/99999?user=김민수" % srv.base)
    assert st == 404


def test_delete_twice_second_is_404(srv, made):
    r = made(room="B", start="16:00", end="16:30", user="한도윤")
    assert http("DELETE", "%s/api/reservations/%s?user=한도윤" % (srv.base, r["res_id"]))[0] == 204
    assert http("DELETE", "%s/api/reservations/%s?user=한도윤" % (srv.base, r["res_id"]))[0] == 404
