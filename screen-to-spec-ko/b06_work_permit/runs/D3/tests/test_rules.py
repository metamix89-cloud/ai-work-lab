import os
import tempfile
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp()
os.environ["PERMIT_DB"] = os.path.join(_tmp, "t.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import clock, db  # noqa: E402
from app.main import app  # noqa: E402
from app.rules import CHECKLISTS, valid_until_for  # noqa: E402

# 시드 사용자: 1,2,3 작업반장 / 4,5 안전담당 / 6,7 현장책임자
T0 = datetime(2026, 11, 6, 10, 0, 0)


@pytest.fixture()
def c():
    p = db.DB_PATH
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(p + ext):
            os.remove(p + ext)
    clock.set_now(T0)
    with TestClient(app) as client:
        yield client
    clock.set_now(None)


def H(uid):
    return {"X-User-Id": str(uid)}


def full(t):
    return {k: True for k in CHECKLISTS[t]}


def apply(c, uid, zone, t):
    r = c.post("/api/permits", json={"zone_id": zone, "work_type": t, "checks": full(t)}, headers=H(uid))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def approve_flow(c, pid, safety=4, boss=6):
    assert c.post(f"/api/permits/{pid}/review", json={}, headers=H(safety)).status_code == 200
    return c.post(f"/api/permits/{pid}/approve", json={}, headers=H(boss))




# ---- 점검 항목 ----
@pytest.mark.parametrize("t", ["고소", "화기", "밀폐"])
def test_each_type_has_three_items(t):
    assert len(CHECKLISTS[t]) == 3


@pytest.mark.parametrize("t", ["고소", "화기", "밀폐"])
def test_missing_any_check_rejected(c, t):
    for k in CHECKLISTS[t]:
        checks = full(t)
        checks[k] = False
        r = c.post("/api/permits", json={"zone_id": 1, "work_type": t, "checks": checks}, headers=H(1))
        assert r.status_code == 422
    # 키 자체가 빠진 경우, 전혀 없는 경우
    r = c.post("/api/permits", json={"zone_id": 1, "work_type": t, "checks": {}}, headers=H(1))
    assert r.status_code == 422


def test_other_type_checks_do_not_count(c):
    r = c.post("/api/permits", json={"zone_id": 1, "work_type": "화기", "checks": full("고소")}, headers=H(1))
    assert r.status_code == 422


def test_unknown_type_and_zone(c):
    assert c.post("/api/permits", json={"zone_id": 1, "work_type": "굴착", "checks": {}}, headers=H(1)).status_code == 422
    assert c.post("/api/permits", json={"zone_id": 99, "work_type": "고소", "checks": full("고소")}, headers=H(1)).status_code == 422


# ---- 순서·권한 ----
def test_cannot_skip_review(c):
    pid = apply(c, 1, 4, "고소")
    assert c.post(f"/api/permits/{pid}/approve", json={}, headers=H(6)).status_code == 409


def test_cannot_start_before_approval(c):
    pid = apply(c, 1, 4, "고소")
    assert c.post(f"/api/permits/{pid}/start", headers=H(1)).status_code == 409
    c.post(f"/api/permits/{pid}/review", json={}, headers=H(4))
    assert c.post(f"/api/permits/{pid}/start", headers=H(1)).status_code == 409


def test_roles_enforced(c):
    pid = apply(c, 1, 4, "고소")
    assert c.post(f"/api/permits/{pid}/review", json={}, headers=H(6)).status_code == 403  # 책임자는 검토 불가
    c.post(f"/api/permits/{pid}/review", json={}, headers=H(4))
    assert c.post(f"/api/permits/{pid}/approve", json={}, headers=H(4)).status_code == 403  # 안전담당은 승인 불가
    assert c.post(f"/api/permits/{pid}/approve", json={}, headers=H(2)).status_code == 403  # 반장은 승인 불가


def test_manager_cannot_approve_own(c):
    pid = apply(c, 6, 4, "고소")  # 현장책임자가 직접 신청
    c.post(f"/api/permits/{pid}/review", json={}, headers=H(4))
    assert c.post(f"/api/permits/{pid}/approve", json={}, headers=H(6)).status_code == 403
    assert c.post(f"/api/permits/{pid}/approve", json={}, headers=H(7)).status_code == 200  # 다른 책임자는 가능


def test_only_applicant_starts_and_ends(c):
    pid = apply(c, 1, 4, "고소")
    approve_flow(c, pid)
    assert c.post(f"/api/permits/{pid}/start", headers=H(2)).status_code == 403
    assert c.post(f"/api/permits/{pid}/start", headers=H(1)).status_code == 200
    assert c.post(f"/api/permits/{pid}/end", headers=H(2)).status_code == 403
    assert c.post(f"/api/permits/{pid}/end", headers=H(1)).status_code == 200


# ---- 유효시간 ----
def test_valid_until_8h_and_midnight_cap():
    assert valid_until_for(datetime(2026, 11, 6, 10, 0, 0)) == datetime(2026, 11, 6, 18, 0, 0)
    assert valid_until_for(datetime(2026, 11, 6, 17, 0, 0)) == datetime(2026, 11, 6, 23, 59, 0)
    assert valid_until_for(datetime(2026, 11, 6, 15, 59, 0)) == datetime(2026, 11, 6, 23, 59, 0)
    assert valid_until_for(datetime(2026, 11, 6, 15, 58, 0)) == datetime(2026, 11, 6, 23, 58, 0)


def test_expiry_blocks_start(c):
    pid = apply(c, 1, 4, "고소")
    approve_flow(c, pid)
    d = c.get(f"/api/permits/{pid}", headers=H(1)).json()
    assert d["valid_until"] == "2026-11-06 18:00:00"
    clock.set_now(T0 + timedelta(hours=8))  # 정확히 만료 시각: 아직 유효
    assert c.get(f"/api/permits/{pid}", headers=H(1)).json()["status"] == "approved"
    clock.set_now(T0 + timedelta(hours=8, seconds=1))
    assert c.get(f"/api/permits/{pid}", headers=H(1)).json()["status"] == "expired"
    r = c.post(f"/api/permits/{pid}/start", headers=H(1))
    assert r.status_code == 409 and "만료" in r.json()["detail"]


def test_cap_at_2359_expiry(c):
    clock.set_now(datetime(2026, 11, 6, 20, 0, 0))
    pid = apply(c, 1, 4, "고소")
    approve_flow(c, pid)
    assert c.get(f"/api/permits/{pid}", headers=H(1)).json()["valid_until"] == "2026-11-06 23:59:00"
    clock.set_now(datetime(2026, 11, 7, 0, 0, 0))  # 8시간 안 지났어도 자정 넘으면 만료
    assert c.get(f"/api/permits/{pid}", headers=H(1)).json()["status"] == "expired"


def test_seeded_yesterday_permit_is_expired(c):
    ps = c.get("/api/permits", headers=H(1)).json()
    assert any(p["status"] == "expired" for p in ps)


def test_no_approval_after_2359(c):
    pid = apply(c, 1, 4, "고소")
    c.post(f"/api/permits/{pid}/review", json={}, headers=H(4))
    clock.set_now(datetime(2026, 11, 6, 23, 59, 30))
    assert c.post(f"/api/permits/{pid}/approve", json={}, headers=H(6)).status_code == 409


# ---- 화기 vs 밀폐 충돌 ----
def test_fire_and_confined_same_zone_conflict(c):
    # 시드: B구역(2)에 승인된 화기가 있음 -> 같은 구역 밀폐는 승인 불가
    seeded = [p for p in c.get("/api/permits", headers=H(6)).json() if p["status"] == "reviewed"][0]
    assert seeded["zone_id"] == 2 and seeded["work_type"] == "밀폐"
    r = c.post(f"/api/permits/{seeded['id']}/approve", json={}, headers=H(6))
    assert r.status_code == 409 and "화기" in r.json()["detail"]


def test_conflict_other_zone_and_same_type_ok(c):
    a = apply(c, 1, 4, "화기"); approve_flow(c, a)
    b = apply(c, 2, 1, "밀폐"); assert approve_flow(c, b).status_code == 200      # 다른 구역
    d = apply(c, 3, 4, "화기"); assert approve_flow(c, d).status_code == 200      # 같은 종류
    e = apply(c, 3, 4, "고소"); assert approve_flow(c, e).status_code == 200      # 고소는 무관


def test_conflict_same_zone(c):
    a = apply(c, 1, 4, "화기"); approve_flow(c, a)
    b = apply(c, 2, 4, "밀폐")
    r = approve_flow(c, b)
    assert r.status_code == 409
    assert c.get(f"/api/permits/{b}", headers=H(2)).json()["status"] == "reviewed"  # 승인 안 됨, 상태 유지


def test_conflict_frees_after_end_or_expiry(c):
    a = apply(c, 1, 4, "화기"); approve_flow(c, a)
    c.post(f"/api/permits/{a}/start", headers=H(1))
    b = apply(c, 2, 4, "밀폐"); c.post(f"/api/permits/{b}/review", json={}, headers=H(4))
    assert c.post(f"/api/permits/{b}/approve", json={}, headers=H(6)).status_code == 409
    clock.set_now(T0 + timedelta(minutes=30))
    c.post(f"/api/permits/{a}/end", headers=H(1))                                   # 종료하면 해소
    assert c.post(f"/api/permits/{b}/approve", json={}, headers=H(6)).status_code == 200


def test_expired_unstarted_does_not_block(c):
    a = apply(c, 1, 4, "화기"); approve_flow(c, a)
    clock.set_now(T0 + timedelta(hours=9))
    b = apply(c, 2, 4, "밀폐"); assert approve_flow(c, b).status_code == 200


def test_working_past_expiry_still_blocks(c):
    a = apply(c, 1, 4, "화기"); approve_flow(c, a)
    c.post(f"/api/permits/{a}/start", headers=H(1))
    clock.set_now(T0 + timedelta(hours=9))  # 유효시간 지났지만 아직 작업 중
    b = apply(c, 2, 4, "밀폐"); c.post(f"/api/permits/{b}/review", json={}, headers=H(4))
    assert c.post(f"/api/permits/{b}/approve", json={}, headers=H(6)).status_code == 409


# ---- 반려 / 조회 ----
def test_reject_requires_reason_and_blocks(c):
    pid = apply(c, 1, 4, "고소")
    assert c.post(f"/api/permits/{pid}/reject", json={"comment": " "}, headers=H(4)).status_code == 422
    assert c.post(f"/api/permits/{pid}/reject", json={"comment": "보완 필요"}, headers=H(4)).status_code == 200
    assert c.post(f"/api/permits/{pid}/review", json={}, headers=H(4)).status_code == 409


def test_visibility_and_dashboard(c):
    assert c.get("/api/dashboard", headers=H(1)).status_code == 403
    d = c.get("/api/dashboard", headers=H(6)).json()
    assert len(d["zones"]) == 4 and d["counts"]
    mine = c.get("/api/permits", headers=H(2)).json()
    assert mine and all(p["applicant_id"] == 2 for p in mine)
    other = [p for p in c.get("/api/permits", headers=H(6)).json() if p["applicant_id"] != 2][0]
    assert c.get(f"/api/permits/{other['id']}", headers=H(2)).status_code == 403
    assert c.get("/api/permits").status_code == 401
