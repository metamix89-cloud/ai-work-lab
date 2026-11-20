# -*- coding: utf-8 -*-
"""회의실 예약 앱 테스트. 서버·고정 데이터는 conftest.py 의 srv 픽스처가 제공한다."""
import pytest

from conftest import DATE, RES, ROOMS, USERS, http

OTHER_DATE = "2026-12-01"   # 고정 데이터에 예약이 없는 날 — 생성 테스트가 서로 간섭하지 않게 쓴다
SLOTS = ["%02d:%02d" % (m // 60, m % 60) for m in range(9 * 60, 18 * 60, 30)]


def url(srv, path):
    return srv.base + path


def body(room="A", date=OTHER_DATE, start="09:00", end="10:00", user="김민수"):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def create(srv, **kw):
    return http("POST", url(srv, "/api/reservations"), body(**kw))


def listing(srv, date):
    st, data = http("GET", url(srv, "/api/reservations?date=" + date))
    assert st == 200
    return data


@pytest.fixture
def clean(srv):
    """테스트가 만든 OTHER_DATE 예약을 끝나고 지운다."""
    yield
    for r in listing(srv, OTHER_DATE):
        http("DELETE", url(srv, "/api/reservations/%d?user=%s" % (r["res_id"], r["user"])))


# ---------- 조회 ----------

def test_list_returns_seed_for_date(srv):
    data = listing(srv, DATE)
    assert len(data) == len(RES)
    got = {(r["res_id"], r["room_id"], r["date"], r["start"], r["end"], r["user"]) for r in data}
    assert got == set(RES)


def test_list_other_date_is_empty(srv):
    assert listing(srv, "2026-11-04") == []


def test_list_requires_date(srv):
    st, _ = http("GET", url(srv, "/api/reservations"))
    assert st == 422


# ---------- 생성 ----------

def test_create_success(srv, clean):
    st, item = create(srv, room="C", start="09:00", end="10:00")
    assert st == 201
    assert item["room_id"] == "C" and item["start"] == "09:00" and item["end"] == "10:00"
    assert item["user"] == "김민수" and item["date"] == OTHER_DATE
    assert item["res_id"] > max(r[0] for r in RES)
    assert item in listing(srv, OTHER_DATE)


def test_create_ids_are_unique(srv, clean):
    _, a = create(srv, room="A", start="09:00", end="10:00")
    _, b = create(srv, room="B", start="09:00", end="10:00")
    assert a["res_id"] != b["res_id"]


def test_create_missing_field_422(srv):
    st, _ = http("POST", url(srv, "/api/reservations"), {"room_id": "A", "date": OTHER_DATE})
    assert st == 422


def test_create_before_opening_rejected(srv):
    st, _ = create(srv, start="08:30", end="09:30")
    assert st == 400


def test_create_after_closing_rejected(srv):
    st, _ = create(srv, start="17:30", end="18:30")
    assert st == 400


def test_create_full_day_boundaries_allowed(srv, clean):
    st, _ = create(srv, room="C", start="09:00", end="18:00")
    assert st == 201


def test_create_exact_overlap_conflict(srv):
    st, _ = create(srv, room="A", date=DATE, start="10:00", end="11:00")
    assert st == 409


def test_create_partial_overlap_conflict(srv):
    st, _ = create(srv, room="A", date=DATE, start="10:30", end="11:30")
    assert st == 409


def test_create_contained_in_existing_conflict(srv):
    st, _ = create(srv, room="C", date=DATE, start="16:30", end="17:00")
    assert st == 409


def test_create_containing_existing_conflict(srv):
    st, _ = create(srv, room="B", date=DATE, start="12:00", end="16:00")
    assert st == 409


def test_conflict_does_not_add_reservation(srv):
    create(srv, room="A", date=DATE, start="10:00", end="11:00")
    assert len(listing(srv, DATE)) == len(RES)


def test_create_different_room_same_time_ok(srv, clean):
    # A 방 10:00-11:00 은 예약돼 있지만 같은 시각 다른 방은 비어 있다. 날짜를 바꿔 독립시킨다.
    st, _ = create(srv, room="C", date=OTHER_DATE, start="10:00", end="11:00")
    assert st == 201


def test_create_same_time_different_date_ok(srv, clean):
    st, _ = create(srv, room="A", date=OTHER_DATE, start="10:00", end="11:00")
    assert st == 201


def test_back_to_back_booking_allowed(srv, clean):
    """끝나는 시각과 시작 시각이 맞닿는 연속 예약(10:00-11:00 뒤 11:00-12:00)은 충돌이 아니다."""
    assert create(srv, room="A", start="10:00", end="11:00")[0] == 201
    st, _ = create(srv, room="A", start="11:00", end="12:00")
    assert st == 201
    st, _ = create(srv, room="A", start="09:00", end="10:00")
    assert st == 201


def test_back_to_back_with_seed_allowed(srv, clean):
    """고정 데이터의 A 10:00-11:00 바로 뒤 11:00-12:00 은 예약 가능해야 한다."""
    st, item = create(srv, room="A", date=DATE, start="11:00", end="12:00")
    try:
        assert st == 201
    finally:
        if st == 201:
            http("DELETE", url(srv, "/api/reservations/%d?user=%s" % (item["res_id"], item["user"])))


def test_end_must_be_after_start(srv, clean):
    st, _ = create(srv, room="C", start="12:00", end="11:00")
    assert st in (400, 422)


def test_zero_length_rejected(srv, clean):
    st, _ = create(srv, room="C", start="12:00", end="12:00")
    assert st in (400, 422)


def test_unknown_room_rejected(srv, clean):
    st, _ = create(srv, room="Z")
    assert st in (400, 404, 422)


def test_unknown_user_rejected(srv, clean):
    st, _ = create(srv, user="없는사람")
    assert st in (400, 403, 404, 422)


# ---------- 삭제 ----------

def test_delete_own_reservation(srv, clean):
    _, item = create(srv, room="C", start="09:00", end="10:00")
    st, _ = http("DELETE", url(srv, "/api/reservations/%d?user=김민수" % item["res_id"]))
    assert st == 204
    assert item not in listing(srv, OTHER_DATE)


def test_deleted_slot_can_be_rebooked(srv, clean):
    _, item = create(srv, room="C", start="09:00", end="10:00")
    http("DELETE", url(srv, "/api/reservations/%d?user=김민수" % item["res_id"]))
    assert create(srv, room="C", start="09:00", end="10:00")[0] == 201


def test_delete_other_users_reservation_forbidden(srv, clean):
    _, item = create(srv, room="C", start="09:00", end="10:00", user="김민수")
    st, _ = http("DELETE", url(srv, "/api/reservations/%d?user=박지연" % item["res_id"]))
    assert st == 403
    assert item in listing(srv, OTHER_DATE)


def test_delete_without_user_forbidden(srv, clean):
    _, item = create(srv, room="C", start="09:00", end="10:00", user="김민수")
    st, _ = http("DELETE", url(srv, "/api/reservations/%d" % item["res_id"]))
    assert st in (400, 403, 422)
    assert item in listing(srv, OTHER_DATE)


def test_delete_missing_returns_404(srv):
    st, _ = http("DELETE", url(srv, "/api/reservations/99999?user=김민수"))
    assert st == 404


# ---------- 화면 ----------

def grid(page):
    """{방: [슬롯별 셀 글자 18개]}"""
    out = {}
    for tr in page.query_selector_all("tbody tr"):
        room = tr.query_selector("th").inner_text().strip()
        out[room] = [td.inner_text().strip() for td in tr.query_selector_all("td")]
    return out


def test_page_title_and_heading(srv, pw):
    page = pw.new_page()
    page.goto(srv.base + "/?date=" + DATE)
    assert page.title() == "회의실 예약"
    assert "회의실 예약" in page.inner_text("h1")
    page.close()


def test_page_has_rooms_and_slots(srv, pw):
    page = pw.new_page()
    page.goto(srv.base + "/?date=" + DATE)
    g = grid(page)
    assert list(g) == [r[0] for r in ROOMS]
    assert all(len(cells) == len(SLOTS) for cells in g.values())
    heads = [th.inner_text().strip() for th in page.query_selector_all("thead th")][1:]
    assert heads == SLOTS
    page.close()


def test_page_shows_seed_reservations(srv, pw):
    page = pw.new_page()
    page.goto(srv.base + "/?date=" + DATE)
    g = grid(page)
    for _, room, _, start, end, user in RES:
        for i, s in enumerate(SLOTS):
            if start <= s < end:
                assert g[room][i] == user, (room, s)
    # 예약 칸 수 = 30분 단위 합: A 2+1, B 1+4, C 4
    assert sum(1 for cells in g.values() for c in cells if c) == 12
    page.close()


def test_page_other_date_is_empty(srv, pw):
    page = pw.new_page()
    page.goto(srv.base + "/?date=2026-11-04")
    assert not any(c for cells in grid(page).values() for c in cells)
    page.close()


def test_page_reflects_new_reservation(srv, pw, clean):
    create(srv, room="C", start="09:00", end="10:00", user="박지연")
    page = pw.new_page()
    page.goto(srv.base + "/?date=" + OTHER_DATE)
    g = grid(page)
    assert g["C"][0] == "박지연" and g["C"][1] == "박지연"
    assert g["C"][2] == ""
    page.close()


def test_page_user_select_lists_all_users(srv, pw):
    page = pw.new_page()
    page.goto(srv.base + "/?date=" + DATE)
    opts = [o.inner_text().strip() for o in page.query_selector_all("select option")]
    assert opts == USERS
    page.close()
