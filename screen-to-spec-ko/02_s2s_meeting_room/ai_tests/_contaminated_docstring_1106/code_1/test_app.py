# -*- coding: utf-8 -*-
"""회의실 예약 앱 테스트.

검증하는 규칙: 조회 · 예약 생성 · 겹침 거부(붙여 예약은 허용) · 30분 단위 · 09:00~18:00 · 최대 2시간 ·
본인만 취소 · 화면 표(회의실 3 × 30분 18칸).
테스트끼리 영향이 없도록 예약 생성 테스트는 날짜를 각자 따로 쓴다 (srv 는 모듈 단위로 공유됨).
"""
import pytest

from urllib.parse import quote

from conftest import DATE, RES, ROOMS, USERS, http


def url(srv, path):
    return srv.base + path


def post(srv, room, date, start, end, user="김민수"):
    return http("POST", url(srv, "/api/reservations"),
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def delete(srv, res_id, user=None):
    q = "" if user is None else "?user=" + quote(user)
    return http("DELETE", url(srv, "/api/reservations/%s%s" % (res_id, q)))


def listing(srv, date):
    status, body = http("GET", url(srv, "/api/reservations?date=" + date))
    assert status == 200
    return body


# ---------- 조회 ----------

def test_list_returns_seed_reservations(srv):
    body = listing(srv, DATE)
    assert sorted(r["res_id"] for r in body) == [r[0] for r in RES]
    first = next(r for r in body if r["res_id"] == 1)
    assert (first["room_id"], first["start"], first["end"], first["user"]) == ("A", "10:00", "11:00", "김민수")


def test_list_other_date_is_empty(srv):
    assert listing(srv, "2026-12-25") == []


# ---------- 예약 생성 ----------

def test_create_success_returns_201_and_new_id(srv):
    status, body = post(srv, "A", "2026-11-10", "09:00", "10:00")
    assert status == 201
    assert body["res_id"] > max(r[0] for r in RES)
    assert (body["room_id"], body["date"], body["start"], body["end"], body["user"]) == \
           ("A", "2026-11-10", "09:00", "10:00", "김민수")
    assert any(r["res_id"] == body["res_id"] for r in listing(srv, "2026-11-10"))


def test_create_does_not_leak_to_other_date(srv):
    post(srv, "B", "2026-11-11", "09:00", "09:30")
    assert all(r["date"] == DATE for r in listing(srv, DATE))


def test_create_missing_field_rejected(srv):
    status, _ = http("POST", url(srv, "/api/reservations"), {"room_id": "A", "date": "2026-11-12", "start": "09:00"})
    assert status in (400, 422)


# ---------- 겹침 ----------

@pytest.mark.parametrize("start,end", [
    ("10:00", "11:00"),   # 완전히 같음
    ("10:30", "11:30"),   # 뒤쪽 걸침
    ("09:30", "10:30"),   # 앞쪽 걸침
    ("10:30", "11:00"),   # 안에 포함
])
def test_overlap_same_room_is_409(srv, start, end):
    status, _ = post(srv, "A", DATE, start, end, "박지연")
    assert status == 409


def test_overlap_containing_existing_is_409(srv):
    # 기존 C 16:00~18:00 을 완전히 덮는 요청 (길이 2시간 이내)
    status, _ = post(srv, "C", DATE, "16:00", "18:00", "김민수")
    assert status == 409


def test_same_time_other_room_ok(srv):
    # A 10:00~11:00 이 있어도 B 는 같은 시간에 비어 있음
    assert post(srv, "A", "2026-11-05", "10:00", "11:00")[0] == 201
    status, _ = post(srv, "B", "2026-11-05", "10:00", "11:00", "박지연")
    assert status == 201


def test_back_to_back_after_existing_is_allowed(srv):
    assert post(srv, "A", "2026-11-06", "10:00", "11:00")[0] == 201
    status, _ = post(srv, "A", "2026-11-06", "11:00", "12:00", "이서준")
    assert status == 201


def test_back_to_back_before_existing_is_allowed(srv):
    assert post(srv, "A", "2026-11-07", "10:00", "11:00")[0] == 201
    status, _ = post(srv, "A", "2026-11-07", "09:00", "10:00", "이서준")
    assert status == 201


def test_overlap_only_on_same_date(srv):
    # 같은 방 · 같은 시간이어도 날짜가 다르면 충돌 아님
    status, _ = post(srv, "A", "2026-11-04", "10:00", "11:00")
    assert status == 201


def test_rejected_booking_is_not_saved(srv):
    before = len(listing(srv, DATE))
    post(srv, "B", DATE, "13:30", "14:30", "박지연")  # B 13:00~15:00 과 겹침
    assert len(listing(srv, DATE)) == before


# ---------- 시간 규칙 ----------

@pytest.mark.parametrize("start,end", [("08:30", "09:30"), ("08:00", "09:00")])
def test_before_opening_rejected(srv, start, end):
    status, _ = post(srv, "A", "2026-11-13", start, end)
    assert status in (400, 422)


@pytest.mark.parametrize("start,end", [("17:30", "18:30"), ("18:00", "18:30")])
def test_after_closing_rejected(srv, start, end):
    status, _ = post(srv, "A", "2026-11-13", start, end)
    assert status in (400, 422)


def test_booking_up_to_closing_is_ok(srv):
    status, _ = post(srv, "A", "2026-11-13", "17:00", "18:00")
    assert status == 201


@pytest.mark.parametrize("start,end", [("09:10", "10:00"), ("09:00", "09:45"), ("09:15", "09:45")])
def test_non_30min_boundary_rejected(srv, start, end):
    status, _ = post(srv, "B", "2026-11-14", start, end)
    assert status in (400, 422)


@pytest.mark.parametrize("start,end", [("10:00", "10:00"), ("11:00", "10:00")])
def test_empty_or_reversed_range_rejected(srv, start, end):
    status, _ = post(srv, "B", "2026-11-14", start, end)
    assert status in (400, 422)


def test_two_hours_is_allowed(srv):
    status, _ = post(srv, "B", "2026-11-15", "09:00", "11:00")
    assert status == 201


def test_over_two_hours_rejected(srv):
    status, _ = post(srv, "B", "2026-11-16", "09:00", "11:30")
    assert status in (400, 422)


def test_half_hour_is_allowed(srv):
    status, _ = post(srv, "B", "2026-11-17", "12:00", "12:30")
    assert status == 201


# ---------- 취소 ----------

def test_owner_can_cancel(srv):
    status, body = post(srv, "C", "2026-11-18", "09:00", "10:00", "한도윤")
    assert status == 201
    assert delete(srv, body["res_id"], "한도윤")[0] == 204
    assert all(r["res_id"] != body["res_id"] for r in listing(srv, "2026-11-18"))


def test_non_owner_cannot_cancel(srv):
    _, body = post(srv, "C", "2026-11-20", "09:00", "10:00", "최유나")
    status, _ = delete(srv, body["res_id"], "김민수")
    assert status in (401, 403)
    assert any(r["res_id"] == body["res_id"] for r in listing(srv, "2026-11-20"))


def test_cancel_without_user_rejected(srv):
    _, body = post(srv, "C", "2026-11-21", "09:00", "10:00", "이서준")
    status, _ = delete(srv, body["res_id"])
    assert status in (400, 401, 403, 422)
    assert any(r["res_id"] == body["res_id"] for r in listing(srv, "2026-11-21"))


def test_cancel_unknown_id_is_404(srv):
    status, _ = delete(srv, 9999, "김민수")
    assert status == 404


def test_slot_reusable_after_cancel(srv):
    status, body = post(srv, "C", "2026-11-19", "10:00", "11:00", "정하늘")
    assert status == 201
    assert delete(srv, body["res_id"], "정하늘")[0] == 204
    assert post(srv, "C", "2026-11-19", "10:00", "11:00", "한도윤")[0] == 201


# ---------- 화면 ----------

@pytest.fixture
def page(pw, srv):
    p = pw.new_page()
    p.goto(url(srv, "/?date=" + DATE))
    yield p
    p.close()


def test_page_title_and_heading(page):
    assert "회의실" in page.title()
    assert "회의실" in page.inner_text("h1")


def test_page_has_grid_of_rooms_by_slots(page):
    # 방 3개 × 30분 칸 18개 (09:00~18:00) — 본문 행의 칸 수
    rows = page.locator("tbody tr")
    assert rows.count() == len(ROOMS)
    for i in range(rows.count()):
        assert rows.nth(i).locator("td").count() == 18


def test_page_header_has_18_time_slots(page):
    heads = page.locator("thead th")
    texts = [t.strip() for t in heads.all_inner_texts() if t.strip()]
    assert len(texts) == 18
    assert texts[0] == "09:00" and texts[-1] == "17:30"


def test_page_shows_reserver_names_in_grid(page):
    body = page.inner_text("tbody")
    for name in ("김민수", "박지연", "이서준", "최유나"):
        assert name in body


def test_page_reserved_cell_count_matches_seed(page):
    # 시드 예약의 총 30분 칸 수: 2+1+1+4+4 = 12
    filled = page.locator("tbody td").evaluate_all("els => els.filter(e => e.innerText.trim() !== '').length")
    assert filled >= 12


def test_page_user_selector_lists_users(page):
    opts = [t.strip() for t in page.locator("select option").all_inner_texts()]
    for u in USERS:
        assert u in opts
