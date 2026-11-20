# -*- coding: utf-8 -*-
"""회의실 예약 앱 테스트. 서버는 모듈 안에서 공유되므로 각 테스트는 겹치지 않는 방/시간을 쓴다."""
from conftest import DATE, RES, http

OTHER = "2026-11-04"


def url(srv, path):
    return srv.base + path


def book(srv, room="A", date=DATE, start="09:00", end="09:30", user="한도윤"):
    return http("POST", url(srv, "/api/reservations"),
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


# ---------- 조회 ----------

def test_list_returns_seed_for_date(srv):
    st, data = http("GET", url(srv, "/api/reservations?date=" + DATE))
    assert st == 200
    assert sorted(r["res_id"] for r in data) == [r[0] for r in RES]
    first = next(r for r in data if r["res_id"] == 1)
    assert first == {"res_id": 1, "room_id": "A", "date": DATE, "start": "10:00", "end": "11:00", "user": "김민수"}


def test_list_other_date_is_empty(srv):
    assert http("GET", url(srv, "/api/reservations?date=" + OTHER)) == (200, [])


def test_list_requires_date(srv):
    st, _ = http("GET", url(srv, "/api/reservations"))
    assert st == 422


# ---------- 생성 ----------

def test_create_success(srv):
    st, item = book(srv, "A", DATE, "15:00", "16:00", "정하늘")
    assert st == 201
    assert item["res_id"] > max(r[0] for r in RES)
    assert (item["room_id"], item["start"], item["end"], item["user"]) == ("A", "15:00", "16:00", "정하늘")
    _, data = http("GET", url(srv, "/api/reservations?date=" + DATE))
    assert any(r["res_id"] == item["res_id"] for r in data)


def test_create_ids_unique(srv):
    _, a = book(srv, "C", OTHER, "09:00", "09:30")
    _, b = book(srv, "C", OTHER, "10:00", "10:30")
    assert a["res_id"] != b["res_id"]


def test_create_missing_field_422(srv):
    st, _ = http("POST", url(srv, "/api/reservations"), {"room_id": "A", "date": DATE})
    assert st == 422


def test_create_overlap_conflict(srv):
    # 시드 1번: A 10:00-11:00
    st, _ = book(srv, "A", DATE, "10:30", "11:30")
    assert st == 409


def test_create_contained_conflict(srv):
    st, _ = book(srv, "C", DATE, "16:30", "17:00")
    assert st == 409


def test_create_exact_same_slot_conflict(srv):
    st, _ = book(srv, "B", DATE, "10:00", "10:30")
    assert st == 409


def test_create_same_time_other_room_ok(srv):
    # A 10:00-11:00 은 차 있지만 다른 방(C) 은 비어 있음
    st, _ = book(srv, "C", DATE, "10:00", "11:00")
    assert st == 201


def test_create_same_time_other_date_ok(srv):
    st, _ = book(srv, "A", OTHER, "10:00", "11:00")
    assert st == 201


def test_create_back_to_back_after_ok(srv):
    # 시드 1번(A 10:00-11:00) 바로 뒤 11:00-12:00 은 겹치지 않는다
    st, _ = book(srv, "A", DATE, "11:00", "12:00")
    assert st == 201


def test_create_back_to_back_before_ok(srv):
    # 시드 2번(A 14:00-14:30) 바로 앞 13:30-14:00
    st, _ = book(srv, "A", DATE, "13:30", "14:00")
    assert st == 201


def test_create_before_opening_400(srv):
    st, _ = book(srv, "B", DATE, "08:30", "09:30")
    assert st == 400


def test_create_after_closing_400(srv):
    st, _ = book(srv, "B", DATE, "17:30", "18:30")
    assert st == 400


def test_create_boundaries_ok(srv):
    assert book(srv, "B", OTHER, "09:00", "09:30")[0] == 201
    assert book(srv, "B", OTHER, "17:30", "18:00")[0] == 201


def test_create_end_before_start_400(srv):
    st, _ = book(srv, "B", OTHER, "12:00", "11:00")
    assert st == 400


def test_create_zero_length_400(srv):
    st, _ = book(srv, "B", OTHER, "12:00", "12:00")
    assert st == 400


def test_create_unknown_room_rejected(srv):
    st, _ = book(srv, "Z", OTHER, "12:00", "12:30")
    assert st in (400, 404, 422)


def test_create_unknown_user_rejected(srv):
    st, _ = book(srv, "B", OTHER, "13:00", "13:30", "외부인")
    assert st in (400, 403, 404, 422)


# ---------- 삭제 ----------

def test_delete_own_reservation(srv):
    _, item = book(srv, "C", OTHER, "14:00", "14:30", "박지연")
    st, _ = http("DELETE", url(srv, "/api/reservations/%d?user=박지연" % item["res_id"]))
    assert st == 204
    _, data = http("GET", url(srv, "/api/reservations?date=" + OTHER))
    assert all(r["res_id"] != item["res_id"] for r in data)


def test_delete_frees_slot(srv):
    _, item = book(srv, "C", OTHER, "15:00", "15:30", "박지연")
    http("DELETE", url(srv, "/api/reservations/%d?user=박지연" % item["res_id"]))
    assert book(srv, "C", OTHER, "15:00", "15:30", "이서준")[0] == 201


def test_delete_others_reservation_forbidden(srv):
    _, item = book(srv, "C", OTHER, "16:00", "16:30", "박지연")
    st, _ = http("DELETE", url(srv, "/api/reservations/%d?user=최유나" % item["res_id"]))
    assert st == 403
    _, data = http("GET", url(srv, "/api/reservations?date=" + OTHER))
    assert any(r["res_id"] == item["res_id"] for r in data)


def test_delete_missing_returns_404(srv):
    st, _ = http("DELETE", url(srv, "/api/reservations/99999?user=김민수"))
    assert st == 404


# ---------- 화면 ----------

def cells(page):
    return page.eval_on_selector_all(
        "tbody tr", "trs => trs.map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))")


def test_index_page_basic(srv, pw):
    page = pw.new_page()
    page.goto(srv.base + "/?date=2026-12-25")   # 예약 없는 날 — 다른 테스트가 만든 예약과 무관
    assert page.title() == "회의실 예약"
    assert page.locator("h1").inner_text() == "다온소프트 회의실 예약"
    assert page.locator("tbody tr").count() == 3
    assert page.locator("thead th").count() == 1 + 18      # 빈 칸 + 09:00~17:30 30분 칸 18개
    assert page.locator("thead th").nth(1).inner_text() == "09:00"
    assert page.locator("thead th").last.inner_text() == "17:30"
    assert all(c == "" for row in cells(page) for c in row)
    page.close()


def test_index_page_shows_seed_reservations(srv, pw):
    page = pw.new_page()
    page.goto(srv.base + "/")                      # 기본 날짜 = 시드 날짜
    rows = cells(page)
    a, b, c = rows
    # 슬롯 인덱스: (시각-09:00)/30분
    assert a[2] == "김민수" and a[3] == "김민수"       # A 10:00-11:00
    assert a[10] == "박지연"                           # A 14:00-14:30
    assert b[2] == "이서준"                            # B 10:00-10:30
    assert [b[i] for i in range(8, 12)] == ["김민수"] * 4   # B 13:00-15:00
    assert [c[i] for i in range(14, 18)] == ["최유나"] * 4  # C 16:00-18:00
    page.close()


def test_index_page_shows_new_reservation_and_end_slot_empty(srv, pw):
    book(srv, "B", "2026-12-24", "11:00", "12:00", "정하늘")
    page = pw.new_page()
    page.goto(srv.base + "/?date=2026-12-24")
    b = cells(page)[1]
    assert b[4] == "정하늘" and b[5] == "정하늘"   # 11:00, 11:30
    assert b[6] == "" and b[3] == ""               # 종료 시각(12:00) 칸과 앞 칸은 비어 있어야 함
    page.close()
