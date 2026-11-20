import importlib
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FOREMAN, FOREMAN2, SAFETY, MANAGER, MANAGER2 = 1, 2, 3, 5, 6
DAY = datetime(2026, 11, 6)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PERMIT_DB", str(tmp_path / "t.db"))
    sys.modules.pop("app", None)
    app = importlib.import_module("app")
    clock = {"t": DAY.replace(hour=9)}
    app.now = lambda: clock["t"]
    # DB 는 빈 상태로 시작 (시드 제외) — 사용자/구역만 넣는다
    with app.connect() as c:
        c.execute("DELETE FROM permits"); c.execute("DELETE FROM events")
    client = TestClient(app.app)

    def call(uid, method, path, **kw):
        return client.request(method, "/api" + path, headers={"X-User-Id": str(uid)}, **kw)

    return app, clock, call


def body(app, type_="fire", zone=1, start=10, end=12, **over):
    b = {"type": type_, "zone_id": zone, "description": "t",
         "planned_start": DAY.replace(hour=start).isoformat(), "planned_end": DAY.replace(hour=end).isoformat(),
         "checks": {i["key"]: True for i in app.TYPES[type_]["checklist"]}}
    b.update(over)
    return b


def to_approved(app, call, **kw):
    pid = call(FOREMAN, "POST", "/permits", json=body(app, **kw)).json()["id"]
    assert call(SAFETY, "POST", f"/permits/{pid}/review", json={"decision": "ok"}).status_code == 200
    r = call(MANAGER, "POST", f"/permits/{pid}/approve", json={"decision": "ok"})
    return pid, r


@pytest.mark.parametrize("type_", ["height", "fire", "confined"])
def test_each_type_has_three_items_and_missing_one_is_rejected(env, type_):
    app, _, call = env
    assert len(app.TYPES[type_]["checklist"]) == 3
    for item in app.TYPES[type_]["checklist"]:
        b = body(app, type_)
        b["checks"][item["key"]] = False
        r = call(FOREMAN, "POST", "/permits", json=b)
        assert r.status_code == 422
    b = body(app, type_); del b["checks"][app.TYPES[type_]["checklist"][0]["key"]]
    assert call(FOREMAN, "POST", "/permits", json=b).status_code == 422
    assert call(FOREMAN, "POST", "/permits", json=body(app, type_)).status_code == 201


def test_order_and_roles(env):
    app, _, call = env
    pid = call(FOREMAN, "POST", "/permits", json=body(app)).json()["id"]
    # 검토 전 승인 불가
    assert call(MANAGER, "POST", f"/permits/{pid}/approve", json={"decision": "ok"}).status_code == 409
    # 작업반장은 검토 불가, 안전 담당은 승인 불가
    assert call(FOREMAN2, "POST", f"/permits/{pid}/review", json={"decision": "ok"}).status_code == 403
    call(SAFETY, "POST", f"/permits/{pid}/review", json={"decision": "ok"})
    assert call(SAFETY, "POST", f"/permits/{pid}/approve", json={"decision": "ok"}).status_code == 403
    # 승인 전 시작 불가
    assert call(FOREMAN, "POST", f"/permits/{pid}/start").status_code == 409


def test_cannot_approve_own_even_manager(env):
    app, _, call = env
    pid = call(MANAGER, "POST", "/permits", json=body(app, "height")).json()["id"]
    call(SAFETY, "POST", f"/permits/{pid}/review", json={"decision": "ok"})
    assert call(MANAGER, "POST", f"/permits/{pid}/approve", json={"decision": "ok"}).status_code == 403
    assert call(MANAGER2, "POST", f"/permits/{pid}/approve", json={"decision": "ok"}).status_code == 200


def test_validity_8h_and_start_end(env):
    app, clock, call = env
    pid, r = to_approved(app, call, type_="height")
    assert r.json()["valid_until"] == DAY.replace(hour=17).isoformat()
    assert call(FOREMAN2, "POST", f"/permits/{pid}/start").status_code == 403  # 신청자만
    assert call(FOREMAN, "POST", f"/permits/{pid}/start").status_code == 200
    assert call(FOREMAN, "POST", f"/permits/{pid}/end").status_code == 200


def test_validity_capped_at_2359(env):
    app, clock, call = env
    clock["t"] = DAY.replace(hour=20)
    pid = call(FOREMAN, "POST", "/permits", json=body(app, "height", start=21, end=23)).json()["id"]
    call(SAFETY, "POST", f"/permits/{pid}/review", json={"decision": "ok"})
    r = call(MANAGER, "POST", f"/permits/{pid}/approve", json={"decision": "ok"})
    assert r.json()["valid_until"] == DAY.replace(hour=23, minute=59).isoformat()


def test_expired_cannot_start(env):
    app, clock, call = env
    pid, _ = to_approved(app, call, type_="height")
    clock["t"] = DAY.replace(hour=17, minute=0, second=1)
    r = call(FOREMAN, "POST", f"/permits/{pid}/start")
    assert r.status_code == 409 and "만료" in r.json()["detail"]
    assert call(FOREMAN, "GET", "/permits?scope=mine").json()[0]["status"] == "expired"
    # 17:00 정각까지는 유효
    clock["t"] = DAY.replace(hour=9)
    pid2, _ = to_approved(app, call, type_="height", start=9, end=18)
    clock["t"] += timedelta(hours=8)
    assert call(FOREMAN, "POST", f"/permits/{pid2}/start").status_code == 200


def test_fire_and_confined_overlap_blocked(env):
    app, _, call = env
    to_approved(app, call, type_="fire", zone=1, start=10, end=12)
    pid = call(FOREMAN2, "POST", "/permits", json=body(app, "confined", zone=1, start=11, end=14)).json()["id"]
    call(SAFETY, "POST", f"/permits/{pid}/review", json={"decision": "ok"})
    assert call(MANAGER, "POST", f"/permits/{pid}/approve", json={"decision": "ok"}).status_code == 409


def test_overlap_rule_only_fire_vs_confined_same_zone_same_time(env):
    app, _, call = env
    to_approved(app, call, type_="fire", zone=1, start=10, end=12)
    # 다른 구역 / 겹치지 않는 시간(경계 맞닿음) / 고소 작업은 허용
    for kw in (dict(type_="confined", zone=2, start=10, end=12),
               dict(type_="confined", zone=1, start=12, end=14),
               dict(type_="height", zone=1, start=10, end=12)):
        assert to_approved(app, call, **kw)[1].status_code == 200, kw
    # 같은 종류끼리는 허용
    assert to_approved(app, call, type_="fire", zone=1, start=10, end=12)[1].status_code == 200


def test_completed_fire_no_longer_blocks_confined(env):
    app, _, call = env
    pid, _ = to_approved(app, call, type_="fire", zone=1, start=10, end=12)
    call(FOREMAN, "POST", f"/permits/{pid}/start"); call(FOREMAN, "POST", f"/permits/{pid}/end")
    assert to_approved(app, call, type_="confined", zone=1, start=10, end=12)[1].status_code == 200


def test_reject_needs_reason_and_is_final(env):
    app, _, call = env
    pid = call(FOREMAN, "POST", "/permits", json=body(app)).json()["id"]
    assert call(SAFETY, "POST", f"/permits/{pid}/review", json={"decision": "reject"}).status_code == 422
    assert call(SAFETY, "POST", f"/permits/{pid}/review", json={"decision": "reject", "note": "x"}).status_code == 200
    assert call(MANAGER, "POST", f"/permits/{pid}/approve", json={"decision": "ok"}).status_code == 409


def test_seed_data_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("PERMIT_DB", str(tmp_path / "s.db"))
    sys.modules.pop("app", None)
    app = importlib.import_module("app")
    c = TestClient(app.app)
    h = {"X-User-Id": "1"}
    assert len(c.get("/api/board", headers=h).json()["zones"]) == 5
    assert c.get("/api/permits?scope=all", headers=h).json()
    assert c.get("/").status_code == 200
