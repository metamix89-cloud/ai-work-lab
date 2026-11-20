# -*- coding: utf-8 -*-
"""다온소프트 회의실 예약 — PRD.md 기준 테스트.

서버는 모듈 안에서 한 번만 뜨므로 예약을 만드는 테스트는 각자 다른 날짜(또는 방)를 써서
서로의 상태에 기대지 않는다. 고정 데이터(DATE)의 5건은 읽기 전용으로만 쓴다.
"""
import pytest

from urllib.parse import quote

from conftest import DATE, RES, ROOMS, USERS, http

SLOTS = ["%02d:%02d" % (m // 60, m % 60) for m in range(9 * 60, 18 * 60, 30)]


def api(srv, path):
    return srv.base + path


def post(srv, room, date, start, end, user="한도윤"):
    return http("POST", api(srv, "/api/reservations"),
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def delete(srv, rid, user=None):
    q = "?user=" + quote(user) if user is not None else ""
    return http("DELETE", api(srv, "/api/reservations/%s%s" % (rid, q)))


def day(srv, date):
    status, body = http("GET", api(srv, "/api/reservations?date=" + date))
    assert status == 200
    return body


# ---------------------------------------------------------------- API: 조회

def test_rooms_api(srv):
    status, body = http("GET", api(srv, "/api/rooms"))
    assert status == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in body] == ROOMS


def test_reservations_api_returns_seed_for_date(srv):
    got = day(srv, DATE)
    assert sorted((r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in got) == sorted(RES)


def test_reservations_api_filters_by_date(srv):
    assert day(srv, "2026-12-25") == []


# ---------------------------------------------------------------- API: 생성/규칙

def test_post_returns_201_and_created_reservation(srv):
    status, body = post(srv, "A", "2026-11-10", "13:00", "14:00", "박지연")
    assert status == 201
    assert (body["room_id"], body["date"], body["start"], body["end"], body["user"]) == \
           ("A", "2026-11-10", "13:00", "14:00", "박지연")
    assert "res_id" in body
    assert [r["res_id"] for r in day(srv, "2026-11-10")] == [body["res_id"]]


@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("10:10", "10:50")])
def test_r1_non_30min_unit_rejected(srv, start, end):
    status, body = post(srv, "C", "2026-11-11", start, end)
    assert status == 400
    assert body["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert day(srv, "2026-11-11") == []


@pytest.mark.parametrize("start,end", [("17:30", "18:30"), ("08:30", "09:30"), ("08:00", "09:00"), ("10:00", "10:00"), ("11:00", "10:30")])
def test_r2_outside_hours_or_reversed_rejected(srv, start, end):
    status, body = post(srv, "C", "2026-11-12", start, end)
    assert status == 400
    assert body["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert day(srv, "2026-11-12") == []


def test_r2_boundaries_allowed(srv):
    assert post(srv, "C", "2026-11-13", "09:00", "09:30")[0] == 201
    assert post(srv, "C", "2026-11-13", "17:30", "18:00")[0] == 201


def test_r3_overlap_rejected_and_count_unchanged(srv):
    before = len(day(srv, DATE))
    status, body = post(srv, "A", DATE, "10:30", "11:30")  # 기존 A 10:00~11:00 과 겹침
    assert status == 409
    assert body["detail"] == "이미 예약된 시간입니다"
    assert len(day(srv, DATE)) == before


@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),  # 완전히 같음
    ("10:00", "10:30"),  # 앞부분
    ("10:30", "11:00"),  # 뒷부분(안쪽)
    ("09:30", "10:30"),  # 앞쪽에 걸침
    ("09:30", "11:30"),  # 감싸 버림
])
def test_r3_overlap_variants(srv, start, end):
    assert post(srv, "A", DATE, start, end)[0] == 409


def test_r3_adjacent_reservations_allowed(srv):
    # 기존 A 10:00~11:00 : 앞 · 뒤로 딱 붙는 예약은 겹침이 아니다
    d = "2026-11-14"
    assert post(srv, "B", d, "10:00", "10:30")[0] == 201
    assert post(srv, "B", d, "10:30", "11:00")[0] == 201
    assert post(srv, "B", d, "09:30", "10:00")[0] == 201
    assert len(day(srv, d)) == 3


def test_r3_adjacent_to_seed_reservation_allowed(srv):
    # 고정 데이터 A 10:00~11:00 바로 뒤(11:00~11:30)는 가능, 바로 앞(09:30~10:00)도 가능
    status, body = post(srv, "A", "2026-11-15", "10:00", "11:00")
    assert status == 201
    assert post(srv, "A", "2026-11-15", "11:00", "11:30")[0] == 201
    assert post(srv, "A", "2026-11-15", "09:30", "10:00")[0] == 201


def test_r3_overlap_on_second_reservation_of_room(srv):
    d = "2026-11-16"
    assert post(srv, "B", d, "10:00", "11:00")[0] == 201
    assert post(srv, "B", d, "14:00", "15:00")[0] == 201
    assert post(srv, "B", d, "14:30", "15:30")[0] == 409


def test_r7_other_room_and_other_date_independent(srv):
    d = "2026-11-17"
    assert post(srv, "A", d, "10:00", "11:00")[0] == 201
    assert post(srv, "B", d, "10:00", "11:00")[0] == 201  # 다른 방
    assert post(srv, "A", "2026-11-18", "10:00", "11:00")[0] == 201  # 다른 날짜


def test_r4_over_two_hours_rejected(srv):
    d = "2026-11-19"
    status, body = post(srv, "C", d, "09:00", "11:30")
    assert status == 400
    assert body["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert day(srv, d) == []


def test_r4_exactly_two_hours_allowed(srv):
    assert post(srv, "C", "2026-11-20", "09:00", "11:00")[0] == 201


def test_r4_two_hours_one_slot_over_rejected(srv):
    assert post(srv, "C", "2026-11-21", "13:00", "15:30")[0] == 400


@pytest.mark.parametrize("field", ["room_id", "date", "start", "end", "user"])
def test_empty_value_rejected(srv, field):
    body = {"room_id": "C", "date": "2026-11-22", "start": "10:00", "end": "10:30", "user": "한도윤"}
    body[field] = ""
    status, _ = http("POST", api(srv, "/api/reservations"), body)
    assert status in (400, 422)
    assert day(srv, "2026-11-22") == []


# ---------------------------------------------------------------- API: 취소 (R5)

def test_r5_delete_other_users_reservation_forbidden(srv):
    # 고정 데이터 res 3 : B 10:00~10:30 이서준
    status, body = delete(srv, 3, "김민수")
    assert status == 403
    assert body["detail"] == "본인 예약만 취소할 수 있습니다"
    assert 3 in [r["res_id"] for r in day(srv, DATE)]


def test_r5_delete_without_user_forbidden(srv):
    status, _ = delete(srv, 3)
    assert status in (403, 422)
    assert 3 in [r["res_id"] for r in day(srv, DATE)]


def test_r5_delete_own_reservation(srv):
    _, created = post(srv, "C", "2026-11-23", "10:00", "11:00", "정하늘")
    rid = created["res_id"]
    status, body = delete(srv, rid, "정하늘")
    assert status == 204
    assert not body
    assert day(srv, "2026-11-23") == []


def test_delete_frees_slot_for_rebooking(srv):
    d = "2026-11-24"
    _, created = post(srv, "C", d, "10:00", "11:00", "정하늘")
    assert post(srv, "C", d, "10:00", "11:00")[0] == 409
    assert delete(srv, created["res_id"], "정하늘")[0] == 204
    assert post(srv, "C", d, "10:00", "11:00")[0] == 201


def test_delete_unknown_id_404(srv):
    status, _ = delete(srv, 99999, "김민수")
    assert status == 404


# ---------------------------------------------------------------- 화면

def open_page(pw, srv, user=None, date=None):
    page = pw.new_page()
    page.goto(srv.base + "/" + ("?date=" + date if date else ""))
    page.wait_for_selector('[data-testid="slot"]', timeout=3000)
    if user:
        page.select_option('[data-testid="user-select"]', user)
        page.wait_for_timeout(300)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


def test_page_opens_with_title(srv, pw):
    page = pw.new_page()
    resp = page.goto(srv.base + "/?date=" + DATE)
    assert resp.status == 200
    assert "회의실" in page.content()
    assert "다온소프트 회의실 예약" in page.inner_text("body")
    page.close()


def test_page_shows_date(srv, pw):
    page = open_page(pw, srv, date=DATE)
    assert DATE in page.locator('[data-testid="date"]').inner_text()
    page.close()


def test_user_select_options_match_users(srv, pw):
    page = open_page(pw, srv, date=DATE)
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts] == USERS
    page.close()


def test_grid_has_54_slots_with_room_and_time_attrs(srv, pw):
    page = open_page(pw, srv, date=DATE)
    slots = page.locator('[data-testid="slot"]')
    assert slots.count() == 54
    found = {(s.get_attribute("data-room"), s.get_attribute("data-start")) for s in slots.all()}
    assert found == {(r[0], t) for r in ROOMS for t in SLOTS}
    assert {s.get_attribute("data-state") for s in slots.all()} <= {"free", "booked", "mine"}
    page.close()


def test_booked_slots_show_other_users(srv, pw):
    page = open_page(pw, srv, user="박지연", date=DATE)
    for start in ("10:00", "10:30"):
        s = slot(page, "A", start)
        assert s.get_attribute("data-state") == "booked"
        assert "김민수" in s.inner_text()
    page.close()


def test_slot_states_for_user_kim(srv, pw):
    page = open_page(pw, srv, user="김민수", date=DATE)
    expected_mine = {("A", "10:00"), ("A", "10:30"),
                     ("B", "13:00"), ("B", "13:30"), ("B", "14:00"), ("B", "14:30")}
    expected_booked = {("A", "14:00"), ("B", "10:00"),
                       ("C", "16:00"), ("C", "16:30"), ("C", "17:00"), ("C", "17:30")}
    for room, _, _ in ROOMS:
        for t in SLOTS:
            want = "mine" if (room, t) in expected_mine else "booked" if (room, t) in expected_booked else "free"
            assert slot(page, room, t).get_attribute("data-state") == want, (room, t)
    page.close()


def test_changing_user_changes_mine(srv, pw):
    page = open_page(pw, srv, user="김민수", date=DATE)
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    page.select_option('[data-testid="user-select"]', "박지연")
    page.wait_for_timeout(300)
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.close()


def test_cancel_button_only_on_mine(srv, pw):
    page = open_page(pw, srv, user="김민수", date=DATE)
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "B", "13:00").locator('[data-testid="cancel-btn"]').count() >= 1
    for room, start in (("A", "14:00"), ("B", "10:00"), ("C", "16:00")):  # 남의 예약
        assert slot(page, room, start).locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "C", "09:00").locator('[data-testid="cancel-btn"]').count() == 0  # 빈 칸
    page.close()


def test_date_query_changes_view(srv, pw):
    page = open_page(pw, srv, user="김민수", date="2026-11-04")
    assert page.locator('[data-testid="slot"]').count() == 54
    assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54
    assert "2026-11-04" in page.locator('[data-testid="date"]').inner_text()
    page.close()


def test_new_reservation_appears_on_page(srv, pw):
    d = "2026-11-25"
    assert post(srv, "B", d, "11:00", "12:00", "이서준")[0] == 201
    page = open_page(pw, srv, user="이서준", date=d)
    assert slot(page, "B", "11:00").get_attribute("data-state") == "mine"
    assert slot(page, "B", "11:30").get_attribute("data-state") == "mine"
    assert slot(page, "B", "12:00").get_attribute("data-state") == "free"
    page.close()


def test_cancel_from_page_removes_reservation(srv, pw):
    d = "2026-11-26"
    _, created = post(srv, "C", d, "15:00", "15:30", "한도윤")
    page = open_page(pw, srv, user="한도윤", date=d)
    page.on("dialog", lambda dlg: dlg.accept())
    btn = slot(page, "C", "15:00").locator('[data-testid="cancel-btn"]')
    assert btn.count() == 1
    btn.click()
    page.wait_for_timeout(500)
    assert slot(page, "C", "15:00").get_attribute("data-state") == "free"
    assert day(srv, d) == []
    page.close()


def test_message_line_exists(srv, pw):
    page = open_page(pw, srv, user="박지연", date=DATE)
    assert page.locator('[data-testid="message"]').count() == 1
    page.close()
