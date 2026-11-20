# -*- coding: utf-8 -*-
"""PRD.md 의 완료 기준(T1~T9)과 업무 규칙(R1~R7)을 검증한다.

테스트끼리 서버 상태(예약)를 공유하므로, 예약을 만드는 테스트는 고정 데이터와
다른 '새 날짜'를 골라 쓴다(날짜가 다르면 서로 간섭하지 않는다).
"""
import itertools
from contextlib import contextmanager

import pytest
from playwright.sync_api import expect

from conftest import DATE, RES, ROOMS, USERS, http

_days = itertools.count(1)


def fresh_date():
    """고정 데이터에 예약이 없는 날짜를 하나씩 내준다."""
    return "2027-02-%02d" % next(_days)


def api(srv, path):
    return srv.base + path


def post(srv, room, date, start, end, user):
    return http("POST", api(srv, "/api/reservations"),
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def listing(srv, date):
    status, body = http("GET", api(srv, "/api/reservations?date=" + date))
    assert status == 200
    return body


def delete(srv, res_id, user):
    return http("DELETE", api(srv, "/api/reservations/%s?user=%s" % (res_id, user)))


@contextmanager
def open_page(pw, srv, date=DATE, user=None):
    page = pw.new_page()
    page.on("dialog", lambda d: d.accept())  # 취소 확인창이 있어도 통과
    try:
        page.goto(srv.base + "/?date=" + date)
        page.wait_for_selector('[data-testid="slot"]')
        if user:
            page.select_option('[data-testid="user-select"]', user)
        yield page
    finally:
        page.close()


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


# ---------------------------------------------------------------- 화면 (T1~T3, T9, R6, F4, F6)

def test_t1_root_opens_with_title(srv, pw):
    status, _ = http("GET", srv.base + "/")
    assert status == 200
    with open_page(pw, srv) as page:
        expect(page.locator("body")).to_contain_text("회의실")
        expect(page.locator("body")).to_contain_text("다온소프트 회의실 예약")


def test_t2_grid_has_54_slots(srv, pw):
    with open_page(pw, srv) as page:
        assert page.locator('[data-testid="slot"]').count() == 3 * 18
        starts = [f"{h:02d}:{m:02d}" for h in range(9, 18) for m in (0, 30)]
        assert len(starts) == 18
        for room, _, _ in ROOMS:
            for s in starts:
                assert slot(page, room, s).count() == 1, (room, s)


def test_screen_header_date_and_user_options(srv, pw):
    with open_page(pw, srv) as page:
        expect(page.locator('[data-testid="date"]')).to_contain_text(DATE)
        options = page.locator('[data-testid="user-select"] option').all_inner_texts()
        assert [o.strip() for o in options] == USERS


def test_t3_seed_reservations_show_as_booked_and_mine(srv, pw):
    with open_page(pw, srv, user="박지연") as page:
        for start in ("10:00", "10:30"):
            expect(slot(page, "A", start)).to_have_attribute("data-state", "booked")
        expect(slot(page, "A", "10:00")).to_contain_text("김민수")
        expect(slot(page, "A", "11:00")).to_have_attribute("data-state", "free")
        expect(slot(page, "A", "14:00")).to_have_attribute("data-state", "mine")
    with open_page(pw, srv, user="김민수") as page:
        for start in ("10:00", "10:30"):
            expect(slot(page, "A", start)).to_have_attribute("data-state", "mine")
        expect(slot(page, "A", "14:00")).to_have_attribute("data-state", "booked")


def test_all_seed_reservations_cover_expected_slots(srv, pw):
    """예약 5건이 칸 상태로 정확히 그려진다 (예약 칸 수 = 시간 / 30분)."""
    expected = {}
    for _, room, _, start, end, user in RES:
        h, m = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        t = h * 60 + m
        while t < eh * 60 + em:
            expected[(room, "%02d:%02d" % divmod(t, 60))] = user
            t += 30
    with open_page(pw, srv, user="한도윤") as page:  # 예약 없는 사용자 → mine 없음
        assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 0
        assert page.locator('[data-testid="slot"][data-state="booked"]').count() == len(expected)
        assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54 - len(expected)
        for (room, start), user in expected.items():
            expect(slot(page, room, start)).to_have_attribute("data-state", "booked")
            expect(slot(page, room, start)).to_contain_text(user)


def test_r6_changing_user_changes_mine(srv, pw):
    with open_page(pw, srv, user="김민수") as page:
        expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "mine")
        expect(slot(page, "B", "13:00")).to_have_attribute("data-state", "mine")
        page.select_option('[data-testid="user-select"]', "이서준")
        expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "booked")
        expect(slot(page, "B", "13:00")).to_have_attribute("data-state", "booked")
        expect(slot(page, "B", "10:00")).to_have_attribute("data-state", "mine")
        page.select_option('[data-testid="user-select"]', "김민수")
        expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "mine")
        expect(slot(page, "B", "10:00")).to_have_attribute("data-state", "booked")


def test_t9_cancel_button_only_on_my_slots(srv, pw):
    with open_page(pw, srv, user="김민수") as page:
        mine = slot(page, "A", "10:00")
        expect(mine).to_have_attribute("data-state", "mine")
        expect(mine.locator('[data-testid="cancel-btn"]')).to_have_count(1)
        booked = slot(page, "A", "14:00")  # 박지연의 예약
        expect(booked).to_have_attribute("data-state", "booked")
        expect(booked.locator('[data-testid="cancel-btn"]')).to_have_count(0)
        free = slot(page, "A", "09:00")
        expect(free.locator('[data-testid="cancel-btn"]')).to_have_count(0)
        # 화면 전체로 봐도 취소 버튼은 mine 칸에만 있다 (김민수: A 2칸 + B 4칸)
        assert page.locator('[data-testid="cancel-btn"]').count() == \
            page.locator('[data-state="mine"] [data-testid="cancel-btn"]').count()
        assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 6


def test_f3_cancel_button_removes_reservation(srv, pw):
    date = fresh_date()
    status, created = post(srv, "C", date, "09:00", "10:00", "정하늘")
    assert status == 201
    with open_page(pw, srv, date=date, user="정하늘") as page:
        expect(slot(page, "C", "09:00")).to_have_attribute("data-state", "mine")
        slot(page, "C", "09:00").locator('[data-testid="cancel-btn"]').first.click()
        expect(slot(page, "C", "09:00")).to_have_attribute("data-state", "free")
        expect(slot(page, "C", "09:30")).to_have_attribute("data-state", "free")
    assert listing(srv, date) == []


def test_f4_date_param_changes_the_timetable(srv, pw):
    date = fresh_date()
    with open_page(pw, srv, date=date, user="김민수") as page:
        expect(page.locator('[data-testid="date"]')).to_contain_text(date)
        assert page.locator('[data-testid="slot"]').count() == 54
        assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54


def test_error_state_when_api_fails(srv, pw):
    page = pw.new_page()
    try:
        page.route("**/api/**", lambda route: route.abort())
        page.goto(srv.base + "/?date=" + DATE)
        expect(page.locator("body")).to_contain_text("불러오지 못했습니다")
        expect(page.get_by_role("button", name="다시")).to_be_visible()
    finally:
        page.close()


# ---------------------------------------------------------------- API 기본 (F4, F5)

def test_f5_rooms_api(srv):
    status, body = http("GET", api(srv, "/api/rooms"))
    assert status == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in body] == ROOMS


def test_f5_reservations_api_returns_seed_for_date(srv):
    body = listing(srv, DATE)
    got = sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in body)
    assert got == sorted(RES)


def test_f4_reservations_filtered_by_date(srv):
    assert listing(srv, "2030-01-01") == []
    date = fresh_date()
    assert post(srv, "A", date, "09:00", "09:30", "김민수")[0] == 201
    assert len(listing(srv, date)) == 1
    assert len(listing(srv, DATE)) == len(RES)  # 다른 날짜는 영향 없음


def test_post_returns_201_and_created_reservation(srv):
    date = fresh_date()
    status, body = post(srv, "B", date, "13:00", "14:00", "박지연")
    assert status == 201
    assert body["room_id"] == "B" and body["date"] == date
    assert body["start"] == "13:00" and body["end"] == "14:00" and body["user"] == "박지연"
    assert "res_id" in body
    assert [r["res_id"] for r in listing(srv, date)] == [body["res_id"]]


def test_post_with_blank_value_is_400(srv):
    date = fresh_date()
    status, body = post(srv, "A", date, "09:00", "10:00", "")
    assert status == 400
    assert "detail" in body
    assert listing(srv, date) == []


# ---------------------------------------------------------------- 업무 규칙 R1~R4, R7

def test_t4_r3_overlap_is_409_and_count_unchanged(srv):
    before = len(listing(srv, DATE))
    status, body = post(srv, "A", DATE, "10:30", "11:30", "박지연")  # A 10:00~11:00 과 부분 겹침
    assert status == 409
    assert body == {"detail": "이미 예약된 시간입니다"}
    assert len(listing(srv, DATE)) == before


@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),  # 완전히 같은 시간
    ("09:30", "10:30"),  # 앞쪽 걸침
    ("10:30", "11:30"),  # 뒤쪽 걸침
    ("10:30", "11:00"),  # 기존 안에 포함
    ("09:30", "11:30"),  # 기존을 감쌈
])
def test_r3_every_overlap_shape_is_409(srv, start, end):
    date = fresh_date()
    assert post(srv, "A", date, "10:00", "11:00", "김민수")[0] == 201
    status, body = post(srv, "A", date, start, end, "박지연")
    assert status == 409
    assert body["detail"] == "이미 예약된 시간입니다"
    assert len(listing(srv, date)) == 1


def test_t5_r3_back_to_back_is_allowed(srv):
    date = fresh_date()
    assert post(srv, "A", date, "10:00", "10:30", "김민수")[0] == 201
    assert post(srv, "A", date, "10:30", "11:00", "박지연")[0] == 201   # 뒤에 붙임
    assert post(srv, "A", date, "09:30", "10:00", "이서준")[0] == 201   # 앞에 붙임
    assert len(listing(srv, date)) == 3


def test_r7_other_rooms_are_independent(srv):
    date = fresh_date()
    assert post(srv, "A", date, "10:00", "11:00", "김민수")[0] == 201
    assert post(srv, "B", date, "10:00", "11:00", "박지연")[0] == 201
    assert post(srv, "C", date, "10:00", "11:00", "이서준")[0] == 201
    assert len(listing(srv, date)) == 3


def test_r3_overlap_only_within_same_date(srv):
    d1, d2 = fresh_date(), fresh_date()
    assert post(srv, "A", d1, "10:00", "11:00", "김민수")[0] == 201
    assert post(srv, "A", d2, "10:00", "11:00", "김민수")[0] == 201


@pytest.mark.parametrize("start,end", [
    ("10:15", "11:00"),   # T6: 시작이 15분
    ("10:00", "10:45"),   # 끝이 45분
    ("10:10", "11:10"),
])
def test_t6_r1_not_30_minute_unit_is_400(srv, start, end):
    date = fresh_date()
    status, body = post(srv, "A", date, start, end, "김민수")
    assert status == 400
    assert body == {"detail": "30분 단위로만 예약할 수 있습니다"}
    assert listing(srv, date) == []


@pytest.mark.parametrize("start,end", [
    ("17:30", "18:30"),   # T6: 18:00 초과
    ("08:30", "09:30"),   # 09:00 이전
    ("08:00", "09:00"),
    ("11:00", "11:00"),   # 길이 0
    ("11:00", "10:30"),   # 끝이 시작보다 앞
])
def test_t6_r2_outside_hours_or_inverted_is_400(srv, start, end):
    date = fresh_date()
    status, body = post(srv, "A", date, start, end, "김민수")
    assert status == 400
    assert body == {"detail": "예약 가능 시간은 09:00~18:00 입니다"}
    assert listing(srv, date) == []


def test_r2_boundaries_are_allowed(srv):
    date = fresh_date()
    assert post(srv, "A", date, "09:00", "09:30", "김민수")[0] == 201    # 첫 칸
    assert post(srv, "A", date, "17:30", "18:00", "김민수")[0] == 201    # 마지막 칸


def test_t7_r4_over_two_hours_is_400(srv):
    date = fresh_date()
    status, body = post(srv, "A", date, "09:00", "11:30", "김민수")  # 2시간 30분
    assert status == 400
    assert body == {"detail": "한 번에 최대 2시간까지 예약할 수 있습니다"}
    assert listing(srv, date) == []


def test_t7_r4_exactly_two_hours_is_201(srv):
    date = fresh_date()
    status, body = post(srv, "A", date, "09:00", "11:00", "김민수")
    assert status == 201
    assert len(listing(srv, date)) == 1


def test_r4_just_over_two_hours_is_400(srv):
    date = fresh_date()
    status, body = post(srv, "B", date, "13:00", "15:30", "김민수")
    assert status == 400
    status, body = post(srv, "B", date, "13:00", "15:00", "김민수")
    assert status == 201


# ---------------------------------------------------------------- 취소 R5 (T8)

def test_t8_r5_delete_by_other_user_is_403_and_stays(srv):
    status, body = delete(srv, 1, "박지연")  # 1번은 김민수의 예약
    assert status == 403
    assert body == {"detail": "본인 예약만 취소할 수 있습니다"}
    assert 1 in [r["res_id"] for r in listing(srv, DATE)]


def test_t8_r5_delete_by_owner_is_204_and_gone(srv):
    date = fresh_date()
    _, created = post(srv, "A", date, "10:00", "11:00", "김민수")
    res_id = created["res_id"]
    status, body = delete(srv, res_id, "김민수")
    assert status == 204
    assert not body
    assert res_id not in [r["res_id"] for r in listing(srv, date)]


def test_delete_missing_reservation_is_404(srv):
    status, _ = delete(srv, 99999, "김민수")
    assert status == 404


def test_cancelled_slot_can_be_booked_again(srv):
    date = fresh_date()
    _, created = post(srv, "C", date, "10:00", "11:00", "김민수")
    assert post(srv, "C", date, "10:00", "11:00", "박지연")[0] == 409
    assert delete(srv, created["res_id"], "김민수")[0] == 204
    assert post(srv, "C", date, "10:00", "11:00", "박지연")[0] == 201
