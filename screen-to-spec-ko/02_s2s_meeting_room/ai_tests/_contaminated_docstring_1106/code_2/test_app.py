# -*- coding: utf-8 -*-
"""회의실 예약 앱 테스트.

규칙: 운영시간 09:00~18:00 · 30분 단위 · 최대 2시간 · 겹치면 409(붙여 예약은 허용) · 예약자 본인만 취소.
서버는 모듈 단위로 하나라서 상태가 공유된다. 그래서 쓰기 테스트는 DATE 가 아닌 날짜(D2, D3 ...)를 쓰고,
DATE 는 고정 데이터 확인용으로 남겨 둔다(충돌 거부 테스트는 DATE 에 쓰지 못하므로 안전).
"""
from urllib.parse import quote

import pytest

from conftest import DATE, RES, ROOMS, USERS, http

D2 = "2026-11-04"


def api(srv):
    return srv.base + "/api/reservations"


def book(srv, room, start, end, user="김민수", date=D2):
    return http("POST", api(srv), {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def cancel(srv, res_id, user=None):
    url = "%s/%s" % (api(srv), res_id)
    if user is not None:
        url += "?user=" + quote(user)
    return http("DELETE", url)


def listing(srv, date):
    st, body = http("GET", api(srv) + "?date=" + date)
    assert st == 200
    return body


# ---------- 조회 ----------

def test_list_returns_seed_for_date(srv):
    body = listing(srv, DATE)
    assert len(body) == len(RES)
    got = {(r["res_id"], r["room_id"], r["start"], r["end"], r["user"]) for r in body}
    want = {(i, rm, s, e, u) for i, rm, _d, s, e, u in RES}
    assert got == want


def test_list_other_date_empty(srv):
    assert listing(srv, "2030-01-01") == []


# ---------- 생성: 정상 ----------

def test_create_returns_201_and_item(srv):
    st, body = book(srv, "A", "09:00", "10:00", date="2026-12-01")
    assert st == 201
    assert body["room_id"] == "A" and body["start"] == "09:00" and body["end"] == "10:00"
    assert body["user"] == "김민수" and isinstance(body["res_id"], int)
    assert any(r["res_id"] == body["res_id"] for r in listing(srv, "2026-12-01"))


def test_create_gets_unique_ids(srv):
    _, a = book(srv, "B", "09:00", "09:30", date="2026-12-02")
    _, b = book(srv, "B", "11:00", "11:30", date="2026-12-02")
    assert a["res_id"] != b["res_id"]
    assert a["res_id"] not in {r[0] for r in RES} and b["res_id"] not in {r[0] for r in RES}


def test_adjacent_after_existing_is_allowed(srv):
    # 고정 데이터 A 10:00~11:00 바로 뒤. 같은 날 같은 방은 DATE 뿐이라 별도 날짜에서 같은 패턴 확인
    st1, _ = book(srv, "A", "10:00", "11:00", date="2026-12-03")
    st2, _ = book(srv, "A", "11:00", "12:00", date="2026-12-03")
    assert (st1, st2) == (201, 201)


def test_adjacent_before_existing_is_allowed(srv):
    st1, _ = book(srv, "A", "10:00", "11:00", date="2026-12-04")
    st2, _ = book(srv, "A", "09:00", "10:00", date="2026-12-04")
    assert (st1, st2) == (201, 201)


def test_same_time_different_room_is_allowed(srv):
    st1, _ = book(srv, "A", "13:00", "14:00", date="2026-12-05")
    st2, _ = book(srv, "B", "13:00", "14:00", date="2026-12-05")
    assert (st1, st2) == (201, 201)


def test_same_time_different_date_is_allowed(srv):
    st1, _ = book(srv, "A", "13:00", "14:00", date="2026-12-06")
    st2, _ = book(srv, "A", "13:00", "14:00", date="2026-12-07")
    assert (st1, st2) == (201, 201)


def test_exactly_two_hours_is_allowed(srv):
    st, _ = book(srv, "C", "09:00", "11:00", date="2026-12-08")
    assert st == 201


def test_full_day_edges_are_allowed(srv):
    assert book(srv, "C", "09:00", "09:30", date="2026-12-09")[0] == 201
    assert book(srv, "C", "17:30", "18:00", date="2026-12-09")[0] == 201


# ---------- 생성: 충돌 ----------

@pytest.mark.parametrize("room,start,end", [
    ("A", "10:00", "11:00"),   # 완전히 같은 시간
    ("A", "10:30", "11:30"),   # 뒤쪽 겹침
    ("A", "09:30", "10:30"),   # 앞쪽 겹침
    ("A", "10:30", "11:00"),   # 안에 포함
    ("B", "12:00", "16:00"),   # 감싸기 (기존 B 13:00~15:00)
    ("C", "17:30", "18:00"),   # 기존 C 16:00~18:00 의 끝부분
])
def test_overlap_is_409(srv, room, start, end):
    st, _ = book(srv, room, start, end, user="박지연", date=DATE)
    assert st == 409


def test_overlap_does_not_create_reservation(srv):
    before = len(listing(srv, DATE))
    book(srv, "A", "10:30", "11:30", date=DATE)
    assert len(listing(srv, DATE)) == before


# ---------- 생성: 잘못된 입력 ----------

@pytest.mark.parametrize("start,end", [
    ("08:30", "09:30"),   # 시작이 운영시간 전
    ("17:30", "18:30"),   # 끝이 운영시간 후
    ("08:00", "08:30"),
    ("18:00", "18:30"),
])
def test_outside_hours_is_400(srv, start, end):
    assert book(srv, "C", start, end, date="2026-12-10")[0] == 400


@pytest.mark.parametrize("start,end", [
    ("11:10", "11:40"),
    ("11:00", "11:45"),
    ("11:15", "12:00"),
])
def test_not_30_minute_unit_is_400(srv, start, end):
    assert book(srv, "C", start, end, date="2026-12-11")[0] == 400


@pytest.mark.parametrize("start,end", [
    ("09:00", "11:30"),   # 2.5시간
    ("09:00", "12:00"),   # 3시간
    ("09:00", "18:00"),
])
def test_over_two_hours_is_400(srv, start, end):
    assert book(srv, "C", start, end, date="2026-12-12")[0] == 400


@pytest.mark.parametrize("start,end", [("11:00", "11:00"), ("12:00", "11:00")])
def test_end_not_after_start_is_400(srv, start, end):
    assert book(srv, "C", start, end, date="2026-12-13")[0] == 400


def test_rejected_booking_is_not_stored(srv):
    book(srv, "C", "09:00", "12:00", date="2026-12-14")
    book(srv, "C", "11:10", "11:40", date="2026-12-14")
    assert listing(srv, "2026-12-14") == []


# ---------- 취소 ----------

def test_owner_can_cancel(srv):
    _, item = book(srv, "A", "15:00", "16:00", user="이서준", date="2026-12-15")
    st, _ = cancel(srv, item["res_id"], "이서준")
    assert st == 204
    assert all(r["res_id"] != item["res_id"] for r in listing(srv, "2026-12-15"))


def test_other_user_cannot_cancel(srv):
    _, item = book(srv, "A", "15:00", "16:00", user="이서준", date="2026-12-16")
    st, _ = cancel(srv, item["res_id"], "박지연")
    assert st == 403
    assert any(r["res_id"] == item["res_id"] for r in listing(srv, "2026-12-16"))


def test_cancel_without_user_is_rejected(srv):
    _, item = book(srv, "A", "15:00", "16:00", user="이서준", date="2026-12-17")
    st, _ = cancel(srv, item["res_id"])
    assert st in (400, 401, 403, 422)
    assert any(r["res_id"] == item["res_id"] for r in listing(srv, "2026-12-17"))


def test_cancel_missing_is_404(srv):
    st, _ = cancel(srv, 99999, "김민수")
    assert st == 404


def test_cancel_frees_the_slot(srv):
    _, item = book(srv, "B", "09:00", "10:00", user="정하늘", date="2026-12-18")
    assert book(srv, "B", "09:00", "10:00", user="한도윤", date="2026-12-18")[0] == 409
    cancel(srv, item["res_id"], "정하늘")
    assert book(srv, "B", "09:00", "10:00", user="한도윤", date="2026-12-18")[0] == 201


# ---------- 화면 ----------

def open_page(pw, srv, date):
    page = pw.new_page()
    page.goto("%s/?date=%s" % (srv.base, date))
    return page


def test_ui_title_and_grid_size(pw, srv):
    page = open_page(pw, srv, DATE)
    try:
        assert "회의실" in page.title()
        assert page.locator("tbody tr").count() == len(ROOMS)
        assert page.locator("tbody td").count() == len(ROOMS) * 18  # 09:00~18:00, 30분 18칸
    finally:
        page.close()


def test_ui_header_has_all_slots(pw, srv):
    page = open_page(pw, srv, DATE)
    try:
        heads = [t.strip() for t in page.locator("thead th").all_inner_texts() if t.strip()]
        assert heads[0] == "09:00" and heads[-1] == "17:30" and len(heads) == 18
    finally:
        page.close()


def test_ui_shows_seed_reservations_in_right_cells(pw, srv):
    page = open_page(pw, srv, DATE)
    try:
        rows = {}
        for tr in page.locator("tbody tr").all():
            cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
            rows[tr.locator("th").inner_text().strip()] = cells
        a, b, c = rows["A"], rows["B"], rows["C"]
        # 칸 번호: (시각-9시)*2
        assert a[2] == "김민수" and a[3] == "김민수" and a[4] == ""
        assert a[10] == "박지연" and a[11] == ""
        assert b[2] == "이서준" and b[3] == ""
        assert b[8:12] == ["김민수"] * 4 and b[12] == ""
        assert c[14:18] == ["최유나"] * 4 and c[13] == ""
        assert sum(1 for r in rows.values() for x in r if x) == 12
    finally:
        page.close()


def test_ui_empty_date_has_no_names(pw, srv):
    page = open_page(pw, srv, "2030-01-01")
    try:
        assert all(not t.strip() for t in page.locator("tbody td").all_inner_texts())
    finally:
        page.close()


def test_ui_reflects_new_reservation(pw, srv):
    st, _ = book(srv, "A", "09:00", "10:00", user="한도윤", date="2026-12-20")
    assert st == 201
    page = open_page(pw, srv, "2026-12-20")
    try:
        row = page.locator("tbody tr").first
        cells = [c.strip() for c in row.locator("td").all_inner_texts()]
        assert cells[0] == "한도윤" and cells[1] == "한도윤" and cells[2] == ""
    finally:
        page.close()


def test_ui_has_user_selector_with_users(pw, srv):
    page = open_page(pw, srv, DATE)
    try:
        opts = page.locator("select option").all_inner_texts()
        assert set(opts) == set(USERS)
    finally:
        page.close()
