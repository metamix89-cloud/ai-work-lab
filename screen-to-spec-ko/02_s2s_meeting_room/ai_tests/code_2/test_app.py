# -*- coding: utf-8 -*-
"""회의실 예약 앱 테스트. srv 는 모듈 단위로 한 번만 뜨므로 테스트끼리 겹치지 않는 방·시간을 쓴다."""
import pytest

from conftest import DATE, ROOMS, USERS, RES, http


def body(room="A", start="09:00", end="09:30", user="김민수", date=DATE):
    return {"room_id": room, "date": date, "start": start, "end": end, "user": user}


def post(srv, b):
    return http("POST", srv.base + "/api/reservations", b)


def listing(srv, date=DATE):
    st, data = http("GET", srv.base + "/api/reservations?date=" + date)
    assert st == 200
    return data


def ids(srv):
    return {x["res_id"] for x in listing(srv)}


# ---------- 조회 ----------
def test_list_returns_seed_reservations(srv):
    data = listing(srv)
    seed = {r[0]: r for r in RES}
    assert set(seed) <= {r["res_id"] for r in data}
    for r in data:
        if r["res_id"] in seed:
            s = seed[r["res_id"]]
            assert (r["room_id"], r["date"], r["start"], r["end"], r["user"]) == s[1:]


def test_list_other_date_is_empty(srv):
    assert listing(srv, "2026-12-25") == []


def test_list_requires_date(srv):
    st, _ = http("GET", srv.base + "/api/reservations")
    assert st == 422


# ---------- 생성 ----------
def test_create_success(srv):
    st, r = post(srv, body("A", "09:00", "09:30", "한도윤"))
    assert st == 201
    assert (r["room_id"], r["start"], r["end"], r["user"]) == ("A", "09:00", "09:30", "한도윤")
    assert r["res_id"] not in {x[0] for x in RES}
    assert r in listing(srv)


def test_create_ids_are_unique(srv):
    st1, a = post(srv, body("C", "09:00", "09:30", "정하늘"))
    st2, b = post(srv, body("B", "09:00", "09:30", "정하늘"))
    assert st1 == 201 and st2 == 201
    assert a["res_id"] != b["res_id"]


def test_create_missing_field_422(srv):
    b = body()
    del b["user"]
    st, _ = post(srv, b)
    assert st == 422


def test_conflict_overlap_409(srv):
    # 시드: A 10:00-11:00
    st, _ = post(srv, body("A", "10:30", "11:30"))
    assert st == 409


def test_conflict_same_slot_409(srv):
    st, _ = post(srv, body("A", "10:00", "11:00", "박지연"))
    assert st == 409


def test_conflict_contained_409(srv):
    # 시드: C 16:00-18:00 안쪽에 포함
    st, _ = post(srv, body("C", "16:30", "17:00"))
    assert st == 409


def test_conflict_containing_409(srv):
    # 시드: B 10:00-10:30 을 감싸는 예약
    st, _ = post(srv, body("B", "09:30", "11:00"))
    assert st == 409


def test_back_to_back_after_is_allowed(srv):
    # 시드 A 10:00-11:00 바로 뒤 11:00 시작은 겹치지 않는다
    st, _ = post(srv, body("A", "11:00", "12:00"))
    assert st == 201


def test_back_to_back_before_is_allowed(srv):
    # 시드 B 13:00-15:00 바로 앞에서 끝나는 예약
    st, _ = post(srv, body("B", "12:00", "13:00"))
    assert st == 201


def test_same_time_other_room_allowed(srv):
    st, _ = post(srv, body("C", "10:00", "11:00"))
    assert st == 201


def test_same_time_other_date_allowed(srv):
    st, _ = post(srv, body("A", "10:00", "11:00", date="2026-11-04"))
    assert st == 201


def test_failed_create_is_not_stored(srv):
    before = len(listing(srv))
    post(srv, body("A", "10:00", "11:00"))
    assert len(listing(srv)) == before


# ---------- 시간 범위 ----------
@pytest.mark.parametrize("start,end", [("08:30", "09:30"), ("17:30", "18:30"), ("07:00", "08:00"), ("19:00", "20:00")])
def test_outside_hours_400(srv, start, end):
    st, _ = post(srv, body("B", start, end))
    assert st == 400


def test_boundary_hours_allowed(srv):
    st, _ = post(srv, body("A", "17:00", "18:00"))
    assert st == 201


@pytest.mark.parametrize("start,end", [("15:00", "14:00"), ("15:00", "15:00")])
def test_end_not_after_start_rejected(srv, start, end):
    st, _ = post(srv, body("B", start, end))
    assert st in (400, 422)


# ---------- 방 · 사용자 검증 ----------
def test_unknown_room_rejected(srv):
    st, _ = post(srv, body("Z", "15:30", "16:00"))
    assert st in (400, 404, 422)


def test_unknown_user_rejected(srv):
    st, _ = post(srv, body("B", "16:00", "16:30", "아무개"))
    assert st in (400, 403, 404, 422)


# ---------- 삭제 ----------
def test_owner_can_delete(srv):
    _, r = post(srv, body("C", "12:00", "12:30", "최유나"))
    st, _ = http("DELETE", srv.base + "/api/reservations/%d?user=최유나" % r["res_id"])
    assert st == 204
    assert r["res_id"] not in ids(srv)


def test_delete_frees_the_slot(srv):
    _, r = post(srv, body("C", "13:00", "13:30", "최유나"))
    http("DELETE", srv.base + "/api/reservations/%d?user=최유나" % r["res_id"])
    st, _ = post(srv, body("C", "13:00", "13:30", "정하늘"))
    assert st == 201


def test_non_owner_cannot_delete(srv):
    _, r = post(srv, body("C", "14:00", "14:30", "정하늘"))
    st, _ = http("DELETE", srv.base + "/api/reservations/%d?user=한도윤" % r["res_id"])
    assert st == 403
    assert r["res_id"] in ids(srv)


def test_delete_without_user_is_rejected(srv):
    _, r = post(srv, body("C", "15:00", "15:30", "정하늘"))
    st, _ = http("DELETE", srv.base + "/api/reservations/%d" % r["res_id"])
    assert st in (400, 401, 403, 422)
    assert r["res_id"] in ids(srv)


def test_delete_missing_returns_404(srv):
    st, _ = http("DELETE", srv.base + "/api/reservations/99999?user=김민수")
    assert st == 404


# ---------- 화면 ----------
@pytest.fixture
def page(pw, srv):
    p = pw.new_page()
    p.goto(srv.base + "/?date=" + DATE)
    yield p
    p.close()


def cell(page, room, slot):
    """room 행, slot("HH:MM") 열의 칸 글자."""
    idx = page.locator("thead th").all_inner_texts().index(slot)
    row = page.locator("tbody tr", has=page.locator("th", has_text=room)).first
    return row.locator("th, td").nth(idx).inner_text()


def test_ui_title_and_grid_shape(page):
    assert "회의실 예약" in page.locator("h1").inner_text()
    assert len(page.locator("thead th").all_inner_texts()) - 1 == 18      # 09:00 ~ 17:30, 30분 단위
    assert page.locator("tbody tr").count() == len(ROOMS)


def test_ui_slot_headers_cover_business_hours(page):
    heads = page.locator("thead th").all_inner_texts()
    assert heads[1] == "09:00" and heads[-1] == "17:30"


def test_ui_shows_seed_reservations(page):
    assert cell(page, "A", "10:00") == "김민수"
    assert cell(page, "A", "10:30") == "김민수"
    assert cell(page, "A", "11:00") == ""
    assert cell(page, "A", "14:00") == "박지연"
    assert cell(page, "A", "14:30") == ""
    assert cell(page, "B", "10:00") == "이서준"
    assert cell(page, "C", "17:30") == "최유나"


def test_ui_other_date_has_no_names(pw, srv):
    p = pw.new_page()
    p.goto(srv.base + "/?date=2027-01-01")
    texts = p.locator("tbody td").all_inner_texts()
    p.close()
    assert not any(t.strip() for t in texts)


def test_ui_user_select_lists_all_users(page):
    assert page.locator("select option").all_inner_texts() == USERS
