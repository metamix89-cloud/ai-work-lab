# -*- coding: utf-8 -*-
"""다온소프트 「회의실 예약」 PRD 검증 테스트 (PRD 3 기능 · 4 화면 · 5 데이터 · 6 업무 규칙 · 10 완료 기준).

격리 원칙
  - 고정 데이터 날짜(DATE)는 읽기 전용. 예약을 만들고 지우는 테스트는 테스트마다 새 날짜(fresh_date)를 쓴다.
    그래서 테스트 순서와 상관없이 서로 영향을 주지 않는다.
"""
import datetime
import itertools
import re

import pytest
from playwright.sync_api import expect

from conftest import DATE, RES, ROOMS, USERS, http

MSG_UNIT = "30분 단위로만 예약할 수 있습니다"
MSG_RANGE = "예약 가능 시간은 09:00~18:00 입니다"
MSG_OVERLAP = "이미 예약된 시간입니다"
MSG_MAX = "한 번에 최대 2시간까지 예약할 수 있습니다"
MSG_OWNER = "본인 예약만 취소할 수 있습니다"

SLOT_STARTS = ["%02d:%02d" % (9 + i // 2, 30 * (i % 2)) for i in range(18)]   # 09:00 ... 17:30
_days = itertools.count()


# ---------------------------------------------------------------- 도우미
def fresh_date():
    """다른 테스트가 건드리지 않은 빈 날짜."""
    return (datetime.date(2027, 1, 1) + datetime.timedelta(days=next(_days))).isoformat()


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def post(srv, room, date, start, end, user):
    return http("POST", srv.base + "/api/reservations",
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def listing(srv, date):
    status, data = http("GET", srv.base + "/api/reservations?date=" + date)
    assert status == 200
    return data


def delete(srv, res_id, user):
    return http("DELETE", "%s/api/reservations/%s?user=%s" % (srv.base, res_id, user))


def book(srv, room, date, start, end, user):
    status, data = post(srv, room, date, start, end, user)
    assert status == 201, (status, data)
    return data


def expected_state(room, start, user, rows=RES):
    """고정 데이터 기준 칸 상태 (R6)."""
    t = to_min(start)
    for _id, r, _d, s, e, u in rows:
        if r == room and to_min(s) <= t < to_min(e):
            return "mine" if u == user else "booked"
    return "free"


@pytest.fixture
def page(pw):
    p = pw.new_page()
    p.set_default_timeout(5000)
    p.on("dialog", lambda d: d.accept())      # 취소 확인창이 있어도 통과
    yield p
    p.close()


def open_board(page, srv, date=DATE, user=None):
    page.goto("%s/?date=%s" % (srv.base, date))
    slots = page.get_by_test_id("slot")
    expect(slots.first).to_be_visible()
    if user:
        page.get_by_test_id("user-select").select_option(label=user)
    return slots


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


# ---------------------------------------------------------------- T1 · 화면 기본
def test_t1_root_opens_with_title(srv, page):
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    expect(page.get_by_text("회의실").first).to_be_visible()


def test_title_text(srv, page):
    page.goto(srv.base + "/")
    expect(page.get_by_text("다온소프트 회의실 예약").first).to_be_visible()


def test_user_select_options_are_seed_users(srv, page):
    open_board(page, srv)
    opts = page.get_by_test_id("user-select").locator("option").all_inner_texts()
    assert [o.strip() for o in opts if o.strip()] == USERS


def test_f4_date_param_shown(srv, page):
    open_board(page, srv, DATE)
    expect(page.get_by_test_id("date")).to_contain_text(DATE)


def test_f4_default_date_is_today(srv, page):
    page.goto(srv.base + "/")
    expect(page.get_by_test_id("date")).to_contain_text(datetime.date.today().isoformat())


# ---------------------------------------------------------------- T2 · 칸 54개
def test_t2_slot_count_is_54(srv, page):
    slots = open_board(page, srv)
    assert slots.count() == 54


def test_slot_grid_rooms_and_times(srv, page):
    slots = open_board(page, srv)
    got = [(s.get_attribute("data-room"), s.get_attribute("data-start")) for s in slots.all()]
    want = [(r[0], t) for r in ROOMS for t in SLOT_STARTS]       # 행 = 회의실 순서, 열 = 09:00 부터 30분
    assert got == want


def test_slot_states_are_only_the_three(srv, page):
    slots = open_board(page, srv)
    states = {s.get_attribute("data-state") for s in slots.all()}
    assert states <= {"free", "booked", "mine"}


def test_other_date_all_free(srv, page):
    slots = open_board(page, srv, fresh_date())
    assert slots.count() == 54
    assert {s.get_attribute("data-state") for s in slots.all()} == {"free"}


# ---------------------------------------------------------------- T3 · 고정 데이터가 칸 상태로
def test_t3_a_1000_1030_booked_then_mine(srv, page):
    open_board(page, srv)
    for start in ("10:00", "10:30"):
        expect(slot(page, "A", start)).to_have_attribute("data-state", "booked")
    page.get_by_test_id("user-select").select_option(label="김민수")
    for start in ("10:00", "10:30"):
        expect(slot(page, "A", start)).to_have_attribute("data-state", "mine")


def test_all_slot_states_match_seed_for_kim(srv, page):
    slots = open_board(page, srv, user="김민수")
    expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "mine")
    for s in slots.all():
        room, start = s.get_attribute("data-room"), s.get_attribute("data-start")
        assert s.get_attribute("data-state") == expected_state(room, start, "김민수"), (room, start)


def test_booked_and_mine_slots_show_user_name(srv, page):
    open_board(page, srv, user="김민수")
    expect(slot(page, "A", "10:00")).to_contain_text("김민수")        # mine
    expect(slot(page, "B", "10:00")).to_contain_text("이서준")        # booked
    expect(slot(page, "C", "17:30")).to_contain_text("최유나")        # 16:00~18:00 의 마지막 칸


def test_free_slot_has_no_name_and_no_cancel(srv, page):
    open_board(page, srv, user="김민수")
    s = slot(page, "A", "09:00")
    expect(s).to_have_attribute("data-state", "free")
    assert s.get_by_test_id("cancel-btn").count() == 0


def test_r6_switching_user_changes_mine(srv, page):
    open_board(page, srv, user="김민수")
    expect(slot(page, "A", "14:00")).to_have_attribute("data-state", "booked")
    page.get_by_test_id("user-select").select_option(label="박지연")
    expect(slot(page, "A", "14:00")).to_have_attribute("data-state", "mine")
    expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "booked")
    expect(slot(page, "B", "13:00")).to_have_attribute("data-state", "booked")


def test_user_without_reservations_sees_no_mine(srv, page):
    slots = open_board(page, srv, user="한도윤")
    expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "booked")
    assert "mine" not in {s.get_attribute("data-state") for s in slots.all()}


# ---------------------------------------------------------------- T9 · 취소 버튼 (R5 화면)
def test_t9_cancel_button_only_on_mine(srv, page):
    slots = open_board(page, srv, user="김민수")
    expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "mine")
    assert slot(page, "A", "10:00").get_by_test_id("cancel-btn").count() >= 1
    assert slot(page, "B", "13:00").get_by_test_id("cancel-btn").count() >= 1
    for s in slots.all():
        has = s.get_by_test_id("cancel-btn").count() > 0
        assert has == (s.get_attribute("data-state") == "mine"), (s.get_attribute("data-room"), s.get_attribute("data-start"))
    assert slot(page, "A", "14:00").get_by_test_id("cancel-btn").count() == 0      # 박지연 예약
    assert slot(page, "B", "10:00").get_by_test_id("cancel-btn").count() == 0      # 이서준 예약


def test_cancel_button_total_matches_mine_slots(srv, page):
    open_board(page, srv, user="김민수")
    mine = page.locator('[data-testid="slot"][data-state="mine"]').count()
    assert mine == 6                                         # A 10:00·10:30 + B 13:00~14:30 네 칸
    assert page.get_by_test_id("cancel-btn").count() == mine


def test_cancel_via_ui_removes_reservation(srv, page):
    d = fresh_date()
    rid = book(srv, "A", d, "11:00", "11:30", "김민수")["res_id"]
    open_board(page, srv, d, user="김민수")
    expect(slot(page, "A", "11:00")).to_have_attribute("data-state", "mine")
    slot(page, "A", "11:00").get_by_test_id("cancel-btn").click()
    expect(slot(page, "A", "11:00")).to_have_attribute("data-state", "free")
    assert all(r["res_id"] != rid for r in listing(srv, d))


# ---------------------------------------------------------------- F2 · 화면에서 예약
def test_book_via_ui_form(srv, page):
    d = fresh_date()
    open_board(page, srv, d, user="이서준")
    slot(page, "C", "09:30").click()
    # 예약 폼의 data-testid 는 PRD 에 없다 — 끝 선택 상자(30·60·90·120분)와 제출 버튼을 역할로 찾는다.
    end_select = page.locator('select:not([data-testid="user-select"])').first
    expect(end_select).to_be_visible()
    end_select.select_option(index=1)                        # 두 번째 선택지 = 60분
    page.get_by_role("button", name=re.compile("예약")).first.click()
    expect(slot(page, "C", "09:30")).to_have_attribute("data-state", "mine")
    expect(slot(page, "C", "10:00")).to_have_attribute("data-state", "mine")
    expect(slot(page, "C", "10:30")).to_have_attribute("data-state", "free")
    rows = listing(srv, d)
    assert [(r["room_id"], r["start"], r["end"], r["user"]) for r in rows] == [("C", "09:30", "10:30", "이서준")]


# ---------------------------------------------------------------- F6 · 거부 사유를 화면에
def test_f6_server_rejection_detail_shown_in_message(srv, page):
    d = fresh_date()
    open_board(page, srv, d, user="김민수")                   # 화면은 아직 빈 칸으로 보임
    book(srv, "B", d, "15:00", "16:00", "박지연")             # 그 사이 다른 사람이 같은 칸을 잡음
    slot(page, "B", "15:00").click()
    page.locator('select:not([data-testid="user-select"])').first.select_option(index=0)
    page.get_by_role("button", name=re.compile("예약")).first.click()
    expect(page.get_by_test_id("message")).to_contain_text(MSG_OVERLAP)
    assert [r["user"] for r in listing(srv, d)] == ["박지연"]


# ---------------------------------------------------------------- 오류 상태
def test_error_state_and_retry(srv, page):
    page.route("**/api/**", lambda route: route.abort())
    page.goto("%s/?date=%s" % (srv.base, DATE))
    expect(page.get_by_text("불러오지 못했습니다")).to_be_visible()
    retry = page.get_by_role("button", name=re.compile("다시"))
    expect(retry).to_be_visible()
    page.unroute("**/api/**")
    retry.click()
    expect(page.get_by_test_id("slot")).to_have_count(54)
    expect(page.get_by_text("불러오지 못했습니다")).to_have_count(0)


# ---------------------------------------------------------------- F5 · 조회 API
def test_api_rooms(srv):
    status, data = http("GET", srv.base + "/api/rooms")
    assert status == 200
    assert data == [{"room_id": r, "name": n, "capacity": c} for r, n, c in ROOMS]


def test_api_reservations_for_seed_date(srv):
    want = [dict(zip(("res_id", "room_id", "date", "start", "end", "user"), r)) for r in RES]
    got = sorted(listing(srv, DATE), key=lambda r: r["res_id"])
    assert got == want


def test_api_reservations_other_date_empty(srv):
    assert listing(srv, fresh_date()) == []


def test_api_reservations_only_requested_date(srv):
    d1, d2 = fresh_date(), fresh_date()
    book(srv, "A", d1, "09:00", "10:00", "김민수")
    book(srv, "A", d2, "13:00", "14:00", "박지연")
    assert [r["date"] for r in listing(srv, d1)] == [d1]
    assert [r["date"] for r in listing(srv, d2)] == [d2]


def test_post_returns_201_and_created_reservation(srv):
    d = fresh_date()
    status, data = post(srv, "A", d, "13:00", "14:00", "박지연")
    assert status == 201
    assert isinstance(data["res_id"], int)
    assert {k: data[k] for k in ("room_id", "date", "start", "end", "user")} == \
        {"room_id": "A", "date": d, "start": "13:00", "end": "14:00", "user": "박지연"}
    assert data in listing(srv, d)


def test_new_reservation_ids_are_unique(srv):
    d = fresh_date()
    ids = [book(srv, "A", d, s, e, "김민수")["res_id"] for s, e in (("09:00", "09:30"), ("09:30", "10:00"), ("10:00", "10:30"))]
    assert len(set(ids)) == 3
    assert not set(ids) & {r[0] for r in RES}


# ---------------------------------------------------------------- R3 · 겹침 (T4, T5, R7)
@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),    # 똑같은 시간
    ("10:30", "11:30"),    # 뒤쪽이 겹침
    ("09:30", "10:30"),    # 앞쪽이 겹침
    ("10:00", "10:30"),    # 기존 안에 포함
    ("09:30", "11:30"),    # 기존을 감쌈
])
def test_t4_overlap_is_409_and_count_unchanged(srv, start, end):
    d = fresh_date()
    book(srv, "A", d, "10:00", "11:00", "김민수")
    before = listing(srv, d)
    status, data = post(srv, "A", d, start, end, "박지연")
    assert status == 409
    assert data == {"detail": MSG_OVERLAP}
    assert listing(srv, d) == before


def test_t4_overlap_with_seed_reservation(srv):
    before = listing(srv, DATE)
    status, data = post(srv, "A", DATE, "10:30", "11:30", "박지연")
    assert (status, data) == (409, {"detail": MSG_OVERLAP})
    assert listing(srv, DATE) == before


@pytest.mark.parametrize("start,end", [("09:30", "10:00"), ("11:00", "11:30")])
def test_t5_back_to_back_is_201(srv, start, end):
    d = fresh_date()
    book(srv, "A", d, "10:00", "11:00", "김민수")
    status, _ = post(srv, "A", d, start, end, "박지연")
    assert status == 201


def test_t5_adjacent_half_hour_slots_both_ok(srv):
    d = fresh_date()
    assert post(srv, "B", d, "10:00", "10:30", "김민수")[0] == 201
    assert post(srv, "B", d, "10:30", "11:00", "박지연")[0] == 201
    assert len(listing(srv, d)) == 2


def test_r7_other_room_same_time_independent(srv):
    d = fresh_date()
    book(srv, "A", d, "10:00", "11:00", "김민수")
    assert post(srv, "B", d, "10:00", "11:00", "박지연")[0] == 201
    assert post(srv, "C", d, "10:00", "11:00", "이서준")[0] == 201


def test_r3_same_room_same_time_other_date_ok(srv):
    d1, d2 = fresh_date(), fresh_date()
    book(srv, "A", d1, "10:00", "11:00", "김민수")
    assert post(srv, "A", d2, "10:00", "11:00", "김민수")[0] == 201


def test_overlap_ui_shows_booked_for_new_reservation(srv, page):
    d = fresh_date()
    book(srv, "A", d, "12:00", "13:00", "최유나")
    open_board(page, srv, d, user="김민수")
    for start in ("12:00", "12:30"):
        expect(slot(page, "A", start)).to_have_attribute("data-state", "booked")
    expect(slot(page, "A", "13:00")).to_have_attribute("data-state", "free")


# ---------------------------------------------------------------- R1 · 30분 단위 (T6)
@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("10:10", "10:50"), ("10:01", "11:00")])
def test_r1_non_half_hour_is_400(srv, start, end):
    d = fresh_date()
    status, data = post(srv, "A", d, start, end, "김민수")
    assert status == 400
    assert data == {"detail": MSG_UNIT}
    assert listing(srv, d) == []


@pytest.mark.parametrize("start,end", [("09:00", "09:30"), ("13:30", "14:00"), ("10:00", "11:00")])
def test_r1_half_hour_units_accepted(srv, start, end):
    assert post(srv, "C", fresh_date(), start, end, "김민수")[0] == 201


# ---------------------------------------------------------------- R2 · 09:00~18:00 (T6)
@pytest.mark.parametrize("start,end", [
    ("17:30", "18:30"),    # 끝이 18:00 넘음
    ("08:30", "09:30"),    # 시작이 09:00 전
    ("18:00", "18:30"),
    ("08:00", "08:30"),
    ("10:00", "10:00"),    # 길이 0
    ("11:00", "10:30"),    # 끝이 시작보다 앞
])
def test_r2_outside_hours_or_reversed_is_400(srv, start, end):
    d = fresh_date()
    status, data = post(srv, "A", d, start, end, "김민수")
    assert status == 400
    assert data == {"detail": MSG_RANGE}
    assert listing(srv, d) == []


@pytest.mark.parametrize("start,end", [("09:00", "09:30"), ("17:30", "18:00"), ("17:00", "18:00")])
def test_r2_boundaries_accepted(srv, start, end):
    assert post(srv, "A", fresh_date(), start, end, "김민수")[0] == 201


# ---------------------------------------------------------------- R4 · 최대 2시간 (T7)
@pytest.mark.parametrize("start,end", [("09:00", "11:30"), ("10:00", "12:30"), ("09:00", "12:00"), ("13:00", "15:30")])
def test_t7_over_two_hours_is_400(srv, start, end):
    d = fresh_date()
    status, data = post(srv, "A", d, start, end, "김민수")
    assert status == 400
    assert data == {"detail": MSG_MAX}
    assert listing(srv, d) == []


@pytest.mark.parametrize("start,end", [("09:00", "11:00"), ("13:00", "15:00"), ("16:00", "18:00"), ("10:00", "11:30")])
def test_t7_up_to_two_hours_is_201(srv, start, end):
    assert post(srv, "B", fresh_date(), start, end, "김민수")[0] == 201


# ---------------------------------------------------------------- 빈 값 (PRD 5: 400 은 빈 값 포함)
@pytest.mark.parametrize("field", ["room_id", "date", "start", "end", "user"])
def test_missing_or_blank_field_is_400(srv, field):
    d = fresh_date()
    body = {"room_id": "A", "date": d, "start": "10:00", "end": "11:00", "user": "김민수"}
    for bad in ("", None):
        body[field] = bad
        status, data = http("POST", srv.base + "/api/reservations", body)
        assert status == 400, (field, bad, status, data)
        assert isinstance(data, dict) and data.get("detail")
    del body[field]
    assert http("POST", srv.base + "/api/reservations", body)[0] in (400, 422)
    assert listing(srv, d) == []


# ---------------------------------------------------------------- R5 · 취소는 본인만 (T8)
def test_t8_delete_others_is_403_and_stays(srv):
    d = fresh_date()
    rid = book(srv, "A", d, "10:00", "11:00", "김민수")["res_id"]
    status, data = delete(srv, rid, "박지연")
    assert status == 403
    assert data == {"detail": MSG_OWNER}
    assert any(r["res_id"] == rid for r in listing(srv, d))


def test_t8_delete_own_is_204_and_gone(srv):
    d = fresh_date()
    rid = book(srv, "A", d, "10:00", "11:00", "김민수")["res_id"]
    status, data = delete(srv, rid, "김민수")
    assert status == 204
    assert not data
    assert all(r["res_id"] != rid for r in listing(srv, d))


def test_delete_missing_is_404(srv):
    assert delete(srv, 999999, "김민수")[0] == 404


def test_deleted_twice_second_is_404(srv):
    d = fresh_date()
    rid = book(srv, "C", d, "10:00", "10:30", "김민수")["res_id"]
    assert delete(srv, rid, "김민수")[0] == 204
    assert delete(srv, rid, "김민수")[0] == 404


def test_delete_frees_the_slot_for_rebooking(srv):
    d = fresh_date()
    rid = book(srv, "A", d, "10:00", "11:00", "김민수")["res_id"]
    assert post(srv, "A", d, "10:00", "11:00", "박지연")[0] == 409
    assert delete(srv, rid, "김민수")[0] == 204
    assert post(srv, "A", d, "10:00", "11:00", "박지연")[0] == 201


def test_delete_other_users_seed_reservation_is_403(srv):
    # 고정 데이터 2번(A 14:00~14:30 박지연)을 김민수가 지우려 한다 — 읽기 전용으로 거부만 확인
    status, data = delete(srv, 2, "김민수")
    assert (status, data) == (403, {"detail": MSG_OWNER})
    assert any(r["res_id"] == 2 for r in listing(srv, DATE))
