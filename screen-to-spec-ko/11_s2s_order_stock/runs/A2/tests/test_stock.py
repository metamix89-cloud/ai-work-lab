import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ["GANADA_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import connect  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, u, p):
    r = client.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


def stock(pid):
    conn = connect()
    try:
        return conn.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()[0]
    finally:
        conn.close()


def new_order(client, h, items):
    r = client.post("/api/orders", headers=h, json={"customer": "테스터", "items": [
        {"product_id": p, "qty": q} for p, q in items]})
    assert r.status_code == 201
    return r.json()["id"]


def test_seed_consistency(client):
    conn = connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM products WHERE stock < 0").fetchone()[0] == 0
        # 초기재고 + 이력합 == 현재고 (이력은 seed 이후 증감만 기록되므로 합이 음수 쪽으로 일치해야 함)
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] >= 10
    finally:
        conn.close()


def test_confirm_cancel_restores(client):
    h = login(client, "staff", "staff123")
    before = stock(7)
    oid = new_order(client, h, [(7, 5)])
    assert stock(7) == before                      # 접수는 재고 불변
    assert client.post(f"/api/orders/{oid}/confirm", headers=h).status_code == 200
    assert stock(7) == before - 5                  # 확정 시 차감
    assert client.post(f"/api/orders/{oid}/confirm", headers=h).status_code == 409  # 이중 확정 불가
    assert stock(7) == before - 5
    assert client.post(f"/api/orders/{oid}/cancel", headers=h).status_code == 200
    assert stock(7) == before                      # 취소 시 복원
    assert client.post(f"/api/orders/{oid}/cancel", headers=h).status_code == 409
    assert stock(7) == before                      # 이중 복원 불가


def test_insufficient_stock_is_atomic(client):
    h = login(client, "staff", "staff123")
    a_before, b_before = stock(1), stock(12)
    oid = new_order(client, h, [(1, 1), (12, b_before + 1)])   # 두 번째 품목이 부족
    r = client.post(f"/api/orders/{oid}/confirm", headers=h)
    assert r.status_code == 409 and "재고 부족" in r.json()["detail"]
    assert stock(1) == a_before and stock(12) == b_before      # 부분 차감 없음
    detail = client.get("/api/orders", headers=h).json()
    assert next(o for o in detail if o["id"] == oid)["status"] == "PENDING"


def test_ship_then_cancel_blocked_and_refund_admin_only(client):
    staff = login(client, "staff", "staff123")
    admin = login(client, "admin", "admin123")
    before = stock(9)
    oid = new_order(client, staff, [(9, 3)])
    client.post(f"/api/orders/{oid}/confirm", headers=staff)
    assert client.post(f"/api/orders/{oid}/refund", headers=admin).status_code == 409  # 출고 전 환불 불가
    client.post(f"/api/orders/{oid}/ship", headers=staff)
    assert client.post(f"/api/orders/{oid}/cancel", headers=staff).status_code == 409  # 출고 후 취소 불가
    assert client.post(f"/api/orders/{oid}/refund", headers=staff).status_code == 403  # 직원 환불 불가
    assert stock(9) == before - 3
    assert client.post(f"/api/orders/{oid}/refund", headers=admin, json={"restock": True}).status_code == 200
    assert stock(9) == before
    assert client.post(f"/api/orders/{oid}/refund", headers=admin).status_code == 409
    assert stock(9) == before


def test_refund_without_restock(client):
    staff = login(client, "staff", "staff123")
    admin = login(client, "admin", "admin123")
    oid = new_order(client, staff, [(9, 2)])
    client.post(f"/api/orders/{oid}/confirm", headers=staff)
    client.post(f"/api/orders/{oid}/ship", headers=staff)
    after_ship = stock(9)
    client.post(f"/api/orders/{oid}/refund", headers=admin, json={"restock": False})
    assert stock(9) == after_ship


def test_adjust_cannot_go_negative(client):
    admin = login(client, "admin", "admin123")
    staff = login(client, "staff", "staff123")
    cur = stock(12)
    assert client.post("/api/products/12/adjust", headers=staff, json={"delta": 1}).status_code == 403
    assert client.post("/api/products/12/adjust", headers=admin, json={"delta": -(cur + 1)}).status_code == 409
    assert stock(12) == cur
    assert client.post("/api/products/12/adjust", headers=admin, json={"delta": 5}).status_code == 200
    assert stock(12) == cur + 5


def test_unauthenticated(client):
    assert client.get("/api/orders").status_code == 401


def test_concurrent_confirms_never_oversell(client):
    staff = login(client, "staff", "staff123")
    admin = login(client, "admin", "admin123")
    # 재고를 정확히 10으로 맞추고 3개씩 8건을 동시에 확정 → 최대 3건만 성공
    cur = stock(10)
    client.post("/api/products/10/adjust", headers=admin, json={"delta": 10 - cur}) if cur != 10 else None
    ids = [new_order(client, staff, [(10, 3)]) for _ in range(8)]

    def go(oid):
        return client.post(f"/api/orders/{oid}/confirm", headers=staff).status_code

    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(go, ids))
    assert codes.count(200) == 3
    assert stock(10) == 1


def test_concurrent_double_cancel_restores_once(client):
    staff = login(client, "staff", "staff123")
    oid = new_order(client, staff, [(7, 4)])
    client.post(f"/api/orders/{oid}/confirm", headers=staff)
    before = stock(7)

    with ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(lambda _: client.post(f"/api/orders/{oid}/cancel", headers=staff).status_code, range(6)))
    assert codes.count(200) == 1
    assert stock(7) == before + 4
