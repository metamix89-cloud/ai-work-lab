# -*- coding: utf-8 -*-
"""PRD 「회의실 예약」 검증 테스트 — 완료 기준(T1~T9) + 업무 규칙(R1~R7) + API(F5) + 화면(F1~F4, F6).

원칙
- 고정 데이터(conftest 의 DATE · ROOMS · USERS · RES)가 있는 날(DATE)은 **바꾸지 않는다.**
  예약을 만들고 지우는 테스트는 테스트마다 새 날짜(fresh_date)를 써서 서로 영향을 주지 않는다.
- 규칙 거부는 상태 코드뿐 아니라 PRD 가 정한 사유 문구(detail)도 확인한다.
"""
import datetime
import itertools
import re
from urllib.parse import quote

import pytest
from playwright.sync_api import expect

from conftest import DATE, RES, ROOMS, USERS, http

MSG_UNIT = "30분 단위로만 예약할 수 있습니다"
MSG_HOURS = "예약 가능 시간은 09:00~18:00 입니다"
MSG_OVERLAP = "이미 예약된 시간입니다"
MSG_MAX = "한 번에 최대 2시간까지 예약할 수 있습니다"
MSG_NOT_OWNER = "본인 예약만 취소할 수 있습니다"

SLOT_STARTS = ["%02d:%02d" % (9 + i // 2, 30 * (i % 2)) for i in range(18)]  # 09:00 ~ 17:30

_days = itertools.count(1)


# ---------------------------------------------------------------- 도우미
def fresh_date():
    """고정 데이터와 겹치지 않는 빈 날짜 (테스트마다 새로)."""
    return (datetime.date(2027, 1, 1) + datetime.timedelta(days=next(_days))).isoformat()


def post(srv, room, date, start, end, user):
    return http("POST", srv.base + "/api/reservations",
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def listing(srv, date):
    status, body = http("GET", srv.base + "/api/reservations?date=" + date)
    assert status == 200, (status, body)
    return body


def delete(srv, res_id, user):
    return http("DELETE", "%s/api/reservations/%s?user=%s" % (srv.base, res_id, quote(user)))


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def open_page(page, srv, date=None, user=None):
    page.goto(srv.base + ("/?date=" + date if date else "/"))
    page.wait_for_selector('[data-testid="slot"]')
    if user:
        page.select_option('[data-testid="user-select"]', label=user)
    return page


@pytest.fixture
def page(srv, pw):
    p = pw.new_page()
    p.on("dialog", lambda d: d.accept())  # 취소 확인창이 있어도 통과
    yield p
    p.close()


# ================================================================ 화면: T1 · T2 · F1 · F4
def test_T1_root_opens_with_title(srv, page):
    resp = page.goto(srv.base + "/")
    assert resp.status == 200
    expect(page.locator("body")).to_contain_text("회의실")
    expect(page.locator("body")).to_contain_text("다온소프트 회의실 예약")


def test_T2_grid_has_54_slots(srv, page):
    open_page(page, srv, DATE)
    assert page.locator('[data-testid="slot"]').count() == 3 * 18


def test_F1_rows_follow_rooms_csv_and_columns_are_30min_from_0900(srv, page):
    open_page(page, srv, DATE)
    slots = page.locator('[data-testid="slot"]')
    pairs = [(slots.nth(i).get_attribute("data-room"), slots.nth(i).get_attribute("data-start"))
             for i in range(slots.count())]
    expected = [(r[0], s) for r in ROOMS for s in SLOT_STARTS]
    assert pairs == expected  # 회의실 A·B·C 순서, 각 행 09:00~17:30 18칸


def test_F1_every_slot_has_one_of_three_states(srv, page):
    open_page(page, srv, DATE)
    states = page.locator('[data-testid="slot"]').evaluate_all("els => els.map(e => e.dataset.state)")
    assert set(states) <= {"free", "booked", "mine"}


def test_F4_date_param_is_shown(srv, page):
    open_page(page, srv, DATE)
    expect(page.locator('[data-testid="date"]')).to_contain_text(DATE)


def test_F4_default_date_is_today(srv, page):
    open_page(page, srv)
    expect(page.locator('[data-testid="date"]')).to_contain_text(datetime.date.today().isoformat())


def test_F4_other_date_shows_only_free_slots(srv, page):
    open_page(page, srv, fresh_date(), user="김민수")
    assert page.locator('[data-testid="slot"]').count() == 54
    assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54


def test_user_select_options_are_users_csv(srv, page):
    open_page(page, srv, DATE)
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts if o.strip()] == USERS


# ================================================================ 화면: T3 · R6 · T9
def test_T3_seed_reservations_show_as_booked_for_others(srv, page):
    open_page(page, srv, DATE, user="박지연")
    for start in ("10:00", "10:30"):
        el = slot(page, "A", start)
        expect(el).to_have_attribute("data-state", "booked")
        expect(el).to_contain_text("김민수")


def test_T3_selecting_owner_turns_booked_into_mine(srv, page):
    open_page(page, srv, DATE, user="김민수")
    for start in ("10:00", "10:30"):
        el = slot(page, "A", start)
        expect(el).to_have_attribute("data-state", "mine")
        expect(el).to_contain_text("김민수")


def test_T3_seed_state_of_every_slot(srv, page):
    """고정 데이터 전체: 예약 칸 12개는 booked/mine, 나머지 42개는 free."""
    def cells(res):
        out = set()
        for _, room, _, s, e, user in res:
            for st in SLOT_STARTS:
                if s <= st < e:
                    out.add((room, st, user))
        return out
    expected = cells(RES)
    assert len(expected) == 12
    open_page(page, srv, DATE, user="정하늘")  # 예약이 없는 사용자 → mine 없음
    for room, st, user in expected:
        el = slot(page, room, st)
        expect(el).to_have_attribute("data-state", "booked")
        expect(el).to_contain_text(user)
    assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54 - 12
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 0


def test_R6_switching_user_changes_mine(srv, page):
    open_page(page, srv, DATE, user="김민수")
    expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "mine")
    expect(slot(page, "A", "14:00")).to_have_attribute("data-state", "booked")
    page.select_option('[data-testid="user-select"]', label="박지연")
    expect(slot(page, "A", "10:00")).to_have_attribute("data-state", "booked")
    expect(slot(page, "A", "14:00")).to_have_attribute("data-state", "mine")
    # 김민수의 mine 은 A 2칸 + B 4칸 = 6, 박지연의 mine 은 1칸
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 1


def test_R6_mine_count_for_each_user(srv, page):
    open_page(page, srv, DATE, user="김민수")
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 6
    page.select_option('[data-testid="user-select"]', label="최유나")
    expect(slot(page, "C", "16:00")).to_have_attribute("data-state", "mine")
    assert page.locator('[data-testid="slot"][data-state="mine"]').count() == 4


def test_T9_cancel_button_only_on_mine(srv, page):
    open_page(page, srv, DATE, user="김민수")
    mine = page.locator('[data-testid="slot"][data-state="mine"]')
    booked = page.locator('[data-testid="slot"][data-state="booked"]')
    assert mine.count() == 6 and booked.count() > 0
    for i in range(mine.count()):
        assert mine.nth(i).locator('[data-testid="cancel-btn"]').count() >= 1
    for i in range(booked.count()):
        assert booked.nth(i).locator('[data-testid="cancel-btn"]').count() == 0
    assert page.locator('[data-testid="slot"][data-state="free"] [data-testid="cancel-btn"]').count() == 0


def test_T9_other_users_booked_slot_has_no_cancel_button(srv, page):
    open_page(page, srv, DATE, user="김민수")
    el = slot(page, "A", "14:00")  # 박지연의 예약
    expect(el).to_have_attribute("data-state", "booked")
    assert el.locator('[data-testid="cancel-btn"]').count() == 0


# ================================================================ 화면: 취소 · 예약 폼 · 메시지(F2 · F3 · F6)
def test_F3_cancel_button_cancels_my_reservation(srv, page):
    d = fresh_date()
    status, created = post(srv, "C", d, "11:00", "11:30", "이서준")
    assert status == 201
    open_page(page, srv, d, user="이서준")
    el = slot(page, "C", "11:00")
    expect(el).to_have_attribute("data-state", "mine")
    el.locator('[data-testid="cancel-btn"]').first.click()
    expect(el).to_have_attribute("data-state", "free")
    assert listing(srv, d) == []


def _book_in_form(page, room, start, minutes):
    """빈 칸 클릭 → 끝 선택(분) → 예약 버튼. 폼 요소에는 testid 가 없어 일반 선택자를 쓴다."""
    slot(page, room, start).click()
    end_select = page.locator('select:not([data-testid="user-select"])').first
    end_select.wait_for(state="visible")
    texts = end_select.locator("option").all_inner_texts()
    idx = next(i for i, t in enumerate(texts) if str(minutes) in t)
    end_select.select_option(index=idx)
    page.get_by_role("button", name=re.compile("^(?!.*취소).*(예약|확인|저장)")).first.click()


def test_F2_click_free_slot_and_book(srv, page):
    d = fresh_date()
    open_page(page, srv, d, user="한도윤")
    _book_in_form(page, "B", "13:00", 60)
    expect(slot(page, "B", "13:00")).to_have_attribute("data-state", "mine")
    expect(slot(page, "B", "13:30")).to_have_attribute("data-state", "mine")
    expect(slot(page, "B", "14:00")).to_have_attribute("data-state", "free")
    got = listing(srv, d)
    assert len(got) == 1
    r = got[0]
    assert (r["room_id"], r["date"], r["start"], r["end"], r["user"]) == ("B", d, "13:00", "14:00", "한도윤")


def test_F6_rejection_reason_shown_in_message_line(srv, page):
    d = fresh_date()
    assert post(srv, "A", d, "10:00", "11:00", "김민수")[0] == 201
    open_page(page, srv, d, user="박지연")
    _book_in_form(page, "A", "09:30", 90)  # 09:30~11:00 은 10:00 예약과 겹침
    expect(page.locator('[data-testid="message"]')).to_contain_text(MSG_OVERLAP)
    assert len(listing(srv, d)) == 1


def test_F6_error_state_when_api_fails_and_retry(srv, page):
    page.route("**/api/**", lambda route: route.abort())
    page.goto(srv.base + "/?date=" + DATE)
    expect(page.locator("body")).to_contain_text("불러오지 못했습니다")
    retry = page.get_by_role("button", name=re.compile("다시"))
    expect(retry).to_be_visible()
    page.unroute("**/api/**")
    retry.click()
    page.wait_for_selector('[data-testid="slot"]')
    assert page.locator('[data-testid="slot"]').count() == 54


# ================================================================ API: F5 읽기
def test_F5_get_rooms(srv):
    status, body = http("GET", srv.base + "/api/rooms")
    assert status == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in body] == ROOMS


def test_F5_get_reservations_returns_seed_for_date(srv):
    got = listing(srv, DATE)
    assert sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in got) == sorted(RES)


def test_F5_get_reservations_filters_by_date(srv):
    assert listing(srv, fresh_date()) == []


# ================================================================ T4 · R3 겹침
@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 완전히 같음
    ("10:30", "11:30"),   # 뒤쪽이 겹침
    ("09:30", "10:30"),   # 앞쪽이 겹침
    ("10:00", "10:30"),   # 안에 포함
    ("09:30", "11:30"),   # 감싸는 예약
])
def test_T4_overlap_with_seed_is_409_and_count_unchanged(srv, start, end):
    before = listing(srv, DATE)
    status, body = post(srv, "A", DATE, start, end, "박지연")
    assert status == 409
    assert body == {"detail": MSG_OVERLAP}
    assert listing(srv, DATE) == before


def test_R3_overlap_with_reservation_created_at_runtime(srv):
    d = fresh_date()
    assert post(srv, "A", d, "13:00", "14:00", "김민수")[0] == 201
    status, body = post(srv, "A", d, "13:30", "14:30", "박지연")
    assert (status, body) == (409, {"detail": MSG_OVERLAP})
    assert len(listing(srv, d)) == 1


def test_T5_back_to_back_reservations_are_allowed(srv):
    d = fresh_date()
    assert post(srv, "A", d, "10:00", "10:30", "김민수")[0] == 201
    assert post(srv, "A", d, "10:30", "11:00", "박지연")[0] == 201   # 앞 예약의 end = 시작
    assert post(srv, "A", d, "09:30", "10:00", "이서준")[0] == 201   # 뒤 예약의 start = 끝
    assert len(listing(srv, d)) == 3


def test_T5_back_to_back_next_to_seed_reservation(srv):
    """고정 예약 A 10:00~11:00 옆에 붙여 예약 — 만든 뒤 지워서 DATE 를 원상태로 둔다."""
    created = []
    try:
        for start, end in (("09:30", "10:00"), ("11:00", "11:30")):
            status, body = post(srv, "A", DATE, start, end, "정하늘")
            assert status == 201, (start, end, status, body)
            created.append(body["res_id"])
    finally:
        for rid in created:
            delete(srv, rid, "정하늘")
    assert len(listing(srv, DATE)) == len(RES)


def test_R7_other_room_same_time_is_independent(srv):
    d = fresh_date()
    assert post(srv, "A", d, "10:00", "11:00", "김민수")[0] == 201
    assert post(srv, "B", d, "10:00", "11:00", "박지연")[0] == 201
    assert post(srv, "C", d, "10:00", "11:00", "이서준")[0] == 201


def test_R3_same_room_same_time_on_other_date_is_independent(srv):
    d1, d2 = fresh_date(), fresh_date()
    assert post(srv, "A", d1, "10:00", "11:00", "김민수")[0] == 201
    assert post(srv, "A", d2, "10:00", "11:00", "김민수")[0] == 201


def test_R7_seed_reservation_does_not_block_other_room(srv):
    """A 10:00 은 고정 예약이 있지만 같은 시간 C 는 비어 있다."""
    d = DATE
    status, body = post(srv, "C", d, "10:00", "10:30", "정하늘")
    try:
        assert status == 201, body
    finally:
        if status == 201:
            delete(srv, body["res_id"], "정하늘")


# ================================================================ POST 성공 응답
def test_F2_post_returns_201_and_created_reservation(srv):
    d = fresh_date()
    status, body = post(srv, "C", d, "13:00", "14:00", "박지연")
    assert status == 201
    assert (body["room_id"], body["date"], body["start"], body["end"], body["user"]) == ("C", d, "13:00", "14:00", "박지연")
    assert isinstance(body["res_id"], int)
    assert listing(srv, d) == [body]


def test_F2_new_res_ids_are_unique(srv):
    d = fresh_date()
    ids = [post(srv, "A", d, s, e, "김민수")[1]["res_id"] for s, e in (("09:00", "09:30"), ("09:30", "10:00"), ("10:00", "10:30"))]
    assert len(set(ids)) == 3
    assert not set(ids) & {r[0] for r in RES}


# ================================================================ R1 30분 단위
@pytest.mark.parametrize("start,end", [
    ("10:15", "11:00"),
    ("10:45", "11:30"),
    ("10:00", "10:45"),
    ("10:00", "11:10"),
    ("10:01", "11:00"),
])
def test_T6_R1_not_30min_unit_is_400(srv, start, end):
    d = fresh_date()
    status, body = post(srv, "A", d, start, end, "김민수")
    assert status == 400
    assert body == {"detail": MSG_UNIT}
    assert listing(srv, d) == []


# ================================================================ R2 09:00~18:00
@pytest.mark.parametrize("start,end", [
    ("17:30", "18:30"),   # 끝이 18:00 넘음
    ("08:30", "09:30"),   # 시작이 09:00 전
    ("08:00", "08:30"),   # 통째로 영업시간 밖
    ("18:00", "18:30"),
    ("11:00", "10:00"),   # 끝이 시작보다 앞
    ("11:00", "11:00"),   # 길이 0
])
def test_T6_R2_outside_hours_or_non_positive_is_400(srv, start, end):
    d = fresh_date()
    status, body = post(srv, "A", d, start, end, "김민수")
    assert status == 400
    assert body == {"detail": MSG_HOURS}
    assert listing(srv, d) == []


@pytest.mark.parametrize("start,end", [("09:00", "09:30"), ("17:30", "18:00")])
def test_R2_boundaries_are_inclusive(srv, start, end):
    status, body = post(srv, "A", fresh_date(), start, end, "김민수")
    assert status == 201, body


# ================================================================ R4 최대 2시간
@pytest.mark.parametrize("start,end", [("09:00", "11:30"), ("09:00", "12:00"), ("13:00", "15:30")])
def test_T7_R4_over_2_hours_is_400(srv, start, end):
    d = fresh_date()
    status, body = post(srv, "C", d, start, end, "김민수")
    assert status == 400
    assert body == {"detail": MSG_MAX}
    assert listing(srv, d) == []


@pytest.mark.parametrize("start,end", [("09:00", "11:00"), ("16:00", "18:00"), ("10:30", "12:30")])
def test_T7_R4_exactly_2_hours_is_201(srv, start, end):
    status, body = post(srv, "C", fresh_date(), start, end, "김민수")
    assert status == 201, body


# ================================================================ 빈 값
@pytest.mark.parametrize("field", ["room_id", "date", "start", "end", "user"])
def test_blank_field_is_400_and_nothing_created(srv, field):
    d = fresh_date()
    body = {"room_id": "A", "date": d, "start": "10:00", "end": "11:00", "user": "김민수"}
    body[field] = ""
    status, resp = http("POST", srv.base + "/api/reservations", body)
    assert status == 400, (status, resp)
    assert isinstance(resp, dict) and resp.get("detail")
    assert listing(srv, d) == []


# ================================================================ T8 · R5 취소는 본인만
def test_T8_delete_by_other_user_is_403_and_reservation_stays(srv):
    status, body = delete(srv, 1, "박지연")   # 1번은 김민수의 예약
    assert status == 403
    assert body == {"detail": MSG_NOT_OWNER}
    assert any(r["res_id"] == 1 for r in listing(srv, DATE))


def test_T8_delete_by_owner_is_204_and_reservation_is_gone(srv):
    d = fresh_date()
    status, created = post(srv, "A", d, "15:00", "16:00", "김민수")
    assert status == 201
    status, body = delete(srv, created["res_id"], "김민수")
    assert status == 204
    assert not body
    assert listing(srv, d) == []


def test_T8_other_user_cannot_delete_created_reservation_then_owner_can(srv):
    d = fresh_date()
    rid = post(srv, "B", d, "15:00", "15:30", "이서준")[1]["res_id"]
    assert delete(srv, rid, "정하늘")[0] == 403
    assert [r["res_id"] for r in listing(srv, d)] == [rid]
    assert delete(srv, rid, "이서준")[0] == 204
    assert listing(srv, d) == []


def test_R5_delete_missing_reservation_is_404(srv):
    assert delete(srv, 99999, "김민수")[0] == 404


def test_R5_delete_twice_second_is_404(srv):
    d = fresh_date()
    rid = post(srv, "A", d, "12:00", "12:30", "김민수")[1]["res_id"]
    assert delete(srv, rid, "김민수")[0] == 204
    assert delete(srv, rid, "김민수")[0] == 404


def test_R5_cancelled_slot_can_be_booked_again(srv):
    d = fresh_date()
    rid = post(srv, "A", d, "12:00", "13:00", "김민수")[1]["res_id"]
    assert post(srv, "A", d, "12:00", "13:00", "박지연")[0] == 409
    assert delete(srv, rid, "김민수")[0] == 204
    assert post(srv, "A", d, "12:00", "13:00", "박지연")[0] == 201
