# -*- coding: utf-8 -*-
"""PRD.md 기준 테스트. 서버는 모듈 안에서 공유되므로, 쓰기 테스트는 서로 다른 날짜를 써서 독립시킨다."""
import pytest

from conftest import DATE, RES, ROOMS, USERS, http

CANCEL_MSG = "본인 예약만 취소할 수 있습니다"


def url(srv, path):
    return srv.base + path


def list_res(srv, date=DATE):
    st, body = http("GET", url(srv, "/api/reservations?date=" + date))
    assert st == 200
    return body


def book(srv, room, start, end, user="한도윤", date=DATE):
    return http("POST", url(srv, "/api/reservations"),
                {"room_id": room, "date": date, "start": start, "end": end, "user": user})


def open_page(pw, srv, date=DATE, user=None):
    page = pw.new_page()
    page.goto(url(srv, "/?date=" + date))
    page.wait_for_selector('[data-testid="slot"]', timeout=5000)
    if user:
        page.select_option('[data-testid="user-select"]', user)
    return page


def slot(page, room, start):
    return page.locator('[data-testid="slot"][data-room="%s"][data-start="%s"]' % (room, start))


# ---------- F5 API: 조회 ----------

def test_rooms_api(srv):
    st, body = http("GET", url(srv, "/api/rooms"))
    assert st == 200
    assert [(r["room_id"], r["name"], r["capacity"]) for r in body] == ROOMS


def test_list_reservations_by_date(srv):
    got = list_res(srv)
    exp = [dict(res_id=r[0], room_id=r[1], date=r[2], start=r[3], end=r[4], user=r[5]) for r in RES]
    assert sorted(got, key=lambda r: r["res_id"]) == exp


def test_list_reservations_other_date_empty(srv):
    assert list_res(srv, "2026-12-25") == []


# ---------- R3 겹침 ----------

def test_overlap_exact_same_409(srv):
    d = DATE
    before = len(list_res(srv, d))
    st, body = book(srv, "A", "10:00", "11:00", date=d)
    assert st == 409
    assert body["detail"] == "이미 예약된 시간입니다"
    assert len(list_res(srv, d)) == before


@pytest.mark.parametrize("start,end", [("09:30", "10:30"), ("10:30", "11:30"), ("10:30", "11:00"), ("09:30", "11:30")])
def test_overlap_partial_and_contained_409(srv, start, end):
    st, body = book(srv, "A", start, end)
    assert st == 409
    assert body["detail"] == "이미 예약된 시간입니다"


def test_adjacent_chain_ok(srv):
    # 같은 날 붙여 예약: 한 칸 잡고 그 뒤/앞에 붙인다
    assert book(srv, "C", "12:00", "12:30", date="2026-11-11")[0] == 201
    assert book(srv, "C", "12:30", "13:00", date="2026-11-11")[0] == 201
    assert book(srv, "C", "11:30", "12:00", date="2026-11-11")[0] == 201


def test_adjacent_to_seed_booking_ok(srv):
    # 고정 데이터 A 10:00~11:00 에 끝/시작을 맞댄 예약 (R3: 같은 시각은 겹침 아님)
    st, _ = book(srv, "A", "11:00", "11:30")
    assert st == 201
    st, _ = book(srv, "A", "09:30", "10:00")
    assert st == 201


def test_create_returns_reservation(srv):
    st, body = book(srv, "B", "16:00", "17:00", user="정하늘", date="2026-11-12")
    assert st == 201
    assert body["room_id"] == "B" and body["start"] == "16:00" and body["end"] == "17:00"
    assert body["user"] == "정하늘" and body["date"] == "2026-11-12"
    assert isinstance(body["res_id"], int)
    assert body in list_res(srv, "2026-11-12")


def test_ids_unique_after_create(srv):
    a = book(srv, "A", "09:00", "09:30", date="2026-11-13")[1]
    b = book(srv, "A", "09:30", "10:00", date="2026-11-13")[1]
    assert a["res_id"] != b["res_id"]


# ---------- R7 방/날짜 독립 ----------

def test_other_room_same_time_ok(srv):
    # A 10:00 은 이미 예약, B 10:30~11:00 은 비어 있음. C 10:00 도 비어 있음.
    st, _ = book(srv, "C", "10:00", "11:00")
    assert st == 201


def test_other_date_same_time_ok(srv):
    st, _ = book(srv, "A", "10:00", "11:00", date="2026-11-04")
    assert st == 201


# ---------- R1 30분 단위 ----------

@pytest.mark.parametrize("start,end", [("10:15", "11:00"), ("10:00", "10:45"), ("13:10", "13:40")])
def test_not_30min_unit_400(srv, start, end):
    d = "2026-11-14"
    st, body = book(srv, "A", start, end, date=d)
    assert st == 400
    assert body["detail"] == "30분 단위로만 예약할 수 있습니다"
    assert list_res(srv, d) == []


# ---------- R2 시간대 ----------

@pytest.mark.parametrize("start,end", [("08:30", "09:30"), ("17:30", "18:30"), ("17:00", "19:00"), ("08:00", "08:30")])
def test_out_of_hours_400(srv, start, end):
    d = "2026-11-15"
    st, body = book(srv, "A", start, end, date=d)
    assert st == 400
    assert body["detail"] == "예약 가능 시간은 09:00~18:00 입니다"
    assert list_res(srv, d) == []


@pytest.mark.parametrize("start,end", [("10:00", "10:00"), ("11:00", "10:00")])
def test_end_not_after_start_400(srv, start, end):
    st, body = book(srv, "A", start, end, date="2026-11-15")
    assert st == 400
    assert body["detail"] == "예약 가능 시간은 09:00~18:00 입니다"


def test_boundaries_ok(srv):
    d = "2026-11-16"
    assert book(srv, "A", "09:00", "09:30", date=d)[0] == 201
    assert book(srv, "A", "17:30", "18:00", date=d)[0] == 201


# ---------- R4 최대 2시간 ----------

def test_over_2h_400(srv):
    d = "2026-11-17"
    st, body = book(srv, "A", "09:00", "11:30", date=d)
    assert st == 400
    assert body["detail"] == "한 번에 최대 2시간까지 예약할 수 있습니다"
    assert list_res(srv, d) == []


def test_exactly_2h_ok(srv):
    assert book(srv, "A", "09:00", "11:00", date="2026-11-18")[0] == 201


def test_2h30_not_aligned_start_still_400(srv):
    assert book(srv, "B", "09:30", "12:00", date="2026-11-18")[0] == 400


# ---------- 빈 값 ----------

@pytest.mark.parametrize("field", ["room_id", "start", "end", "user"])
def test_empty_field_400(srv, field):
    body = {"room_id": "A", "date": "2026-11-19", "start": "10:00", "end": "10:30", "user": "김민수"}
    body[field] = ""
    st, _ = http("POST", url(srv, "/api/reservations"), body)
    assert st in (400, 422)
    assert list_res(srv, "2026-11-19") == []


# ---------- R5 취소 ----------

def test_delete_others_403_and_stays(srv):
    st, body = http("DELETE", url(srv, "/api/reservations/1?user=" + "박지연"))
    assert st == 403
    assert body["detail"] == CANCEL_MSG
    assert any(r["res_id"] == 1 for r in list_res(srv))


def test_delete_without_user_403(srv):
    st, _ = http("DELETE", url(srv, "/api/reservations/1"))
    assert st in (400, 403, 422)
    assert any(r["res_id"] == 1 for r in list_res(srv))


def test_delete_own_204_and_gone(srv):
    d = "2026-11-20"
    rid = book(srv, "A", "10:00", "10:30", user="이서준", date=d)[1]["res_id"]
    st, _ = http("DELETE", url(srv, "/api/reservations/%d?user=%s" % (rid, "이서준")))
    assert st == 204
    assert list_res(srv, d) == []
    # 취소 뒤 같은 칸을 다시 예약할 수 있다
    assert book(srv, "A", "10:00", "10:30", user="김민수", date=d)[0] == 201


def test_delete_missing_404(srv):
    st, _ = http("DELETE", url(srv, "/api/reservations/99999?user=" + "김민수"))
    assert st == 404


# ---------- 화면 ----------

def test_index_opens_with_title(srv, pw):
    page = pw.new_page()
    resp = page.goto(url(srv, "/"))
    assert resp.status == 200
    assert "회의실" in page.content()
    page.close()


def test_grid_has_54_slots(srv, pw):
    page = open_page(pw, srv)
    assert page.locator('[data-testid="slot"]').count() == 54
    for room, _, _ in ROOMS:
        assert page.locator('[data-testid="slot"][data-room="%s"]' % room).count() == 18
    starts = page.locator('[data-testid="slot"][data-room="A"]').evaluate_all("els => els.map(e => e.dataset.start)")
    assert starts[0] == "09:00" and starts[-1] == "17:30" and len(set(starts)) == 18
    page.close()


def test_user_select_options_and_date(srv, pw):
    page = open_page(pw, srv)
    opts = page.locator('[data-testid="user-select"] option').all_inner_texts()
    assert [o.strip() for o in opts if o.strip()] == USERS
    assert DATE in page.locator('[data-testid="date"]').inner_text()
    page.close()


def test_date_param_changes_view(srv, pw):
    page = open_page(pw, srv, date="2026-12-25")
    assert "2026-12-25" in page.locator('[data-testid="date"]').inner_text()
    assert page.locator('[data-testid="slot"][data-state="free"]').count() == 54
    page.close()


def test_slot_states_for_other_user(srv, pw):
    page = open_page(pw, srv, user="한도윤")
    for room, start in [("A", "10:00"), ("A", "10:30"), ("A", "14:00"), ("B", "10:00"), ("C", "17:30")]:
        assert slot(page, room, start).get_attribute("data-state") == "booked"
    assert slot(page, "A", "11:00").get_attribute("data-state") == "free"
    assert slot(page, "A", "09:00").get_attribute("data-state") == "free"
    assert page.locator('[data-state="mine"]').count() == 0
    page.close()


def test_booked_slot_shows_name(srv, pw):
    page = open_page(pw, srv, user="한도윤")
    assert "박지연" in slot(page, "A", "14:00").inner_text()
    page.close()


def test_mine_state_and_switching_user(srv, pw):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "mine"
    assert slot(page, "A", "10:30").get_attribute("data-state") == "mine"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "booked"
    # 김민수의 B 13:00~15:00 은 4칸
    assert page.locator('[data-testid="slot"][data-room="B"][data-state="mine"]').count() == 4
    page.select_option('[data-testid="user-select"]', "박지연")
    assert slot(page, "A", "10:00").get_attribute("data-state") == "booked"
    assert slot(page, "A", "14:00").get_attribute("data-state") == "mine"
    page.close()


def test_cancel_button_only_on_mine(srv, pw):
    page = open_page(pw, srv, user="김민수")
    assert slot(page, "A", "10:00").locator('[data-testid="cancel-btn"]').count() >= 1
    assert slot(page, "A", "14:00").locator('[data-testid="cancel-btn"]').count() == 0
    assert slot(page, "A", "11:00").locator('[data-testid="cancel-btn"]').count() == 0
    # 모든 취소 버튼은 mine 칸 안에만 있다
    assert page.locator('[data-state="booked"] [data-testid="cancel-btn"], [data-state="free"] [data-testid="cancel-btn"]').count() == 0
    page.close()


def test_ui_cancel_removes_reservation(srv, pw):
    d = "2026-11-21"
    rid = book(srv, "C", "09:00", "09:30", user="정하늘", date=d)[1]["res_id"]
    page = open_page(pw, srv, date=d, user="정하늘")
    assert slot(page, "C", "09:00").get_attribute("data-state") == "mine"
    slot(page, "C", "09:00").locator('[data-testid="cancel-btn"]').first.click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"slot\"][data-room=\"C\"][data-start=\"09:00\"]').dataset.state === 'free'",
        timeout=5000)
    assert all(r["res_id"] != rid for r in list_res(srv, d))
    page.close()


def test_new_booking_appears_in_ui(srv, pw):
    d = "2026-11-22"
    book(srv, "B", "11:00", "12:00", user="최유나", date=d)
    page = open_page(pw, srv, date=d, user="한도윤")
    assert slot(page, "B", "11:00").get_attribute("data-state") == "booked"
    assert slot(page, "B", "11:30").get_attribute("data-state") == "booked"
    assert slot(page, "B", "12:00").get_attribute("data-state") == "free"
    page.close()


def test_free_slot_click_opens_form(srv, pw):
    page = open_page(pw, srv, user="한도윤")
    before = page.locator("select").count()
    slot(page, "C", "09:00").click()
    # 예약 폼: 끝 시각 선택(30·60·90·120분)이 나타난다
    page.wait_for_timeout(300)
    assert page.locator("select").count() > before or page.locator("form").count() > 0
    page.close()


def test_error_state_when_api_fails(srv, pw):
    page = pw.new_page()
    page.route("**/api/**", lambda route: route.fulfill(status=500, body="boom"))
    page.goto(url(srv, "/?date=" + DATE))
    page.wait_for_selector("text=불러오지 못했습니다", timeout=5000)
    assert page.get_by_role("button").count() >= 1
    page.close()
