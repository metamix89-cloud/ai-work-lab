# -*- coding: utf-8 -*-
"""회의실 예약 앱 테스트. 예약 규칙: 09:00~18:00 · 30분 단위 · 최대 2시간 · 겹침 불가(붙여 예약은 허용) · 본인만 취소."""
from urllib.parse import quote

from conftest import DATE, RES, ROOMS, http

OTHER = "2026-11-04"  # 고정 데이터와 섞이지 않게 쓰는 빈 날짜


def api(srv):
    return srv.base + "/api/reservations"


def book(srv, room, start, end, user="김민수", date=OTHER):
    return http("POST", api(srv), {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def listing(srv, date):
    st, data = http("GET", api(srv) + "?date=" + date)
    assert st == 200
    return data


# ---------- 조회 ----------
def test_list_returns_seed_for_date(srv):
    data = listing(srv, DATE)
    assert sorted(r["res_id"] for r in data) == sorted(r[0] for r in RES)
    first = next(r for r in data if r["res_id"] == 1)
    assert (first["room_id"], first["start"], first["end"], first["user"]) == ("A", "10:00", "11:00", "김민수")


def test_list_other_date_is_empty(srv):
    assert listing(srv, "2030-01-01") == []


# ---------- 생성 ----------
def test_create_success(srv):
    st, body = book(srv, "A", "09:00", "10:00", date="2026-11-10")
    assert st == 201
    assert body["res_id"] not in [r[0] for r in RES]
    assert (body["room_id"], body["start"], body["end"], body["user"]) == ("A", "09:00", "10:00", "김민수")
    assert body in listing(srv, "2026-11-10")


def test_overlap_rejected(srv):
    st, _ = http("POST", api(srv), {"room_id": "A", "date": DATE, "start": "10:30", "end": "11:30", "user": "박지연"})
    assert st == 409


def test_contained_overlap_rejected(srv):
    st, _ = http("POST", api(srv), {"room_id": "B", "date": DATE, "start": "13:30", "end": "14:00", "user": "박지연"})
    assert st == 409


def test_same_time_other_room_allowed(srv):
    st, _ = http("POST", api(srv), {"room_id": "B", "date": DATE, "start": "11:00", "end": "11:30", "user": "박지연"})
    assert st == 201
    st, _ = http("POST", api(srv), {"room_id": "C", "date": DATE, "start": "10:00", "end": "11:00", "user": "박지연"})
    assert st == 201


def test_back_to_back_after_allowed(srv):
    # A 10:00~11:00 바로 뒤
    st, _ = http("POST", api(srv), {"room_id": "A", "date": DATE, "start": "11:00", "end": "12:00", "user": "정하늘"})
    assert st == 201


def test_back_to_back_before_allowed(srv):
    # C 16:00~18:00 바로 앞
    st, _ = http("POST", api(srv), {"room_id": "C", "date": DATE, "start": "15:00", "end": "16:00", "user": "정하늘"})
    assert st == 201


def test_same_slot_other_date_allowed(srv):
    st, _ = book(srv, "A", "10:00", "11:00", date="2026-11-11")
    assert st == 201


def test_before_opening_rejected(srv):
    st, _ = book(srv, "A", "08:30", "09:30", date="2026-11-12")
    assert st in (400, 422)


def test_after_closing_rejected(srv):
    st, _ = book(srv, "A", "17:30", "18:30", date="2026-11-12")
    assert st in (400, 422)


def test_boundaries_allowed(srv):
    assert book(srv, "A", "09:00", "09:30", date="2026-11-13")[0] == 201
    assert book(srv, "A", "17:30", "18:00", date="2026-11-13")[0] == 201


def test_non_30min_unit_rejected(srv):
    st, _ = book(srv, "A", "09:10", "10:00", date="2026-11-14")
    assert st in (400, 422)
    st, _ = book(srv, "A", "09:00", "09:45", date="2026-11-14")
    assert st in (400, 422)


def test_max_two_hours_allowed(srv):
    assert book(srv, "B", "09:00", "11:00", date="2026-11-15")[0] == 201


def test_over_two_hours_rejected(srv):
    st, _ = book(srv, "B", "09:00", "11:30", date="2026-11-16")
    assert st in (400, 422)


def test_end_not_after_start_rejected(srv):
    for s, e in (("10:00", "10:00"), ("11:00", "10:00")):
        st, _ = book(srv, "A", s, e, date="2026-11-17")
        assert st in (400, 422)


def test_missing_fields_rejected(srv):
    st, _ = http("POST", api(srv), {"room_id": "A", "date": OTHER})
    assert st in (400, 422)


def test_rejected_booking_not_stored(srv):
    before = len(listing(srv, "2026-11-18"))
    book(srv, "A", "08:00", "09:00", date="2026-11-18")
    assert len(listing(srv, "2026-11-18")) == before


# ---------- 취소 ----------
def test_owner_can_cancel(srv):
    st, body = book(srv, "C", "09:00", "10:00", user="한도윤", date="2026-11-19")
    assert st == 201
    st, _ = http("DELETE", "%s/%d?user=%s" % (api(srv), body["res_id"], quote("한도윤")))
    assert st == 204
    assert all(r["res_id"] != body["res_id"] for r in listing(srv, "2026-11-19"))


def test_non_owner_cannot_cancel(srv):
    st, body = book(srv, "C", "09:00", "10:00", user="한도윤", date="2026-11-20")
    assert st == 201
    st, _ = http("DELETE", "%s/%d?user=%s" % (api(srv), body["res_id"], quote("정하늘")))
    assert st == 403
    assert any(r["res_id"] == body["res_id"] for r in listing(srv, "2026-11-20"))


def test_cancel_without_user_rejected(srv):
    st, body = book(srv, "C", "11:00", "12:00", user="한도윤", date="2026-11-20")
    assert st == 201
    st, _ = http("DELETE", "%s/%d" % (api(srv), body["res_id"]))
    assert st in (400, 401, 403, 422)
    assert any(r["res_id"] == body["res_id"] for r in listing(srv, "2026-11-20"))


def test_cancel_missing_returns_404(srv):
    st, _ = http("DELETE", api(srv) + "/99999?user=" + quote("김민수"))
    assert st == 404


def test_cancel_frees_slot(srv):
    st, body = book(srv, "A", "12:00", "13:00", user="한도윤", date="2026-11-21")
    assert st == 201
    assert book(srv, "A", "12:00", "13:00", user="정하늘", date="2026-11-21")[0] == 409
    assert http("DELETE", "%s/%d?user=%s" % (api(srv), body["res_id"], quote("한도윤")))[0] == 204
    assert book(srv, "A", "12:00", "13:00", user="정하늘", date="2026-11-21")[0] == 201


# ---------- 화면 ----------
def open_page(pw, srv, date=DATE):
    page = pw.new_page()
    page.goto("%s/?date=%s" % (srv.base, date))
    return page


def test_page_title_and_heading(srv, pw):
    page = open_page(pw, srv)
    try:
        assert "회의실" in page.title()
        assert "회의실 예약" in page.inner_text("h1")
    finally:
        page.close()


def test_page_shows_all_rooms(srv, pw):
    page = open_page(pw, srv)
    try:
        text = page.inner_text("body")
        for rid, _name, _cap in ROOMS:
            assert rid in text
    finally:
        page.close()


def test_page_grid_has_cell_per_room_and_slot(srv, pw):
    # 3개 방 × 09:00~18:00 30분 칸 18개 = 54칸
    page = open_page(pw, srv)
    try:
        assert page.locator("tbody td").count() == len(ROOMS) * 18
    finally:
        page.close()


def test_page_shows_reserved_user_names(srv, pw):
    page = open_page(pw, srv)
    try:
        # 다른 테스트가 DATE 에 예약을 더했을 수 있으니 API 의 현재 예약을 기준으로 삼는다
        cells = page.locator("tbody td").all_inner_texts()
        expected = sum(_slots(r["start"], r["end"]) for r in listing(srv, DATE))
        assert sum(1 for c in cells if c.strip()) == expected
        assert any("박지연" in c for c in cells)
    finally:
        page.close()


def test_page_empty_date_has_no_names(srv, pw):
    page = open_page(pw, srv, "2030-01-01")
    try:
        assert not any(c.strip() for c in page.locator("tbody td").all_inner_texts())
    finally:
        page.close()


def test_page_lists_users_in_select(srv, pw):
    page = open_page(pw, srv)
    try:
        opts = page.locator("select option").all_inner_texts()
        assert "김민수" in opts and "박지연" in opts
    finally:
        page.close()


def _slots(start, end):
    def m(t):
        h, mi = t.split(":")
        return int(h) * 60 + int(mi)
    return (m(end) - m(start)) // 30
