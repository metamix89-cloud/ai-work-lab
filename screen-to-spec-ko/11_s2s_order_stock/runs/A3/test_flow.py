import os, tempfile
os.environ["GANADA_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from fastapi.testclient import TestClient
import main

c = TestClient(main.app)


def login(u, p):
    t = c.post("/api/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


staff, admin = login("staff", "staff123"), login("admin", "admin123")
stock = lambda pid: next(p["stock"] for p in c.get("/api/products", headers=staff).json() if p["id"] == pid)
new = lambda items: c.post("/api/orders", headers=staff, json={"customer": "t", "items": items}).json()["id"]

assert c.get("/api/products").status_code == 401
s0 = stock(1)
o = new([{"product_id": 1, "qty": 5}])
assert stock(1) == s0                                           # 접수만으로는 재고 불변
assert c.post(f"/api/orders/{o}/confirm", headers=staff).status_code == 200 and stock(1) == s0 - 5
assert c.post(f"/api/orders/{o}/confirm", headers=staff).status_code == 409 and stock(1) == s0 - 5  # 중복 확정 차단
assert c.post(f"/api/orders/{o}/ship", headers=staff).status_code == 200 and stock(1) == s0 - 5
assert c.post(f"/api/orders/{o}/cancel", headers=staff).status_code == 409   # 출고 후 취소 불가
assert c.post(f"/api/orders/{o}/refund", headers=staff, json={}).status_code == 403  # 직원 환불 불가
assert c.post(f"/api/orders/{o}/refund", headers=admin, json={"restock": True}).status_code == 200 and stock(1) == s0
assert c.post(f"/api/orders/{o}/refund", headers=admin, json={}).status_code == 409  # 이중 환불 차단

o = new([{"product_id": 1, "qty": 2}]); c.post(f"/api/orders/{o}/confirm", headers=staff)
assert stock(1) == s0 - 2
c.post(f"/api/orders/{o}/cancel", headers=staff); assert stock(1) == s0   # 확정 후 취소 → 복원
o = new([{"product_id": 1, "qty": 2}]); c.post(f"/api/orders/{o}/cancel", headers=staff); assert stock(1) == s0  # 대기 취소 → 불변

# 재고 부족: 전체 롤백 (2번째 상품 부족 → 1번째 차감도 취소)
o = new([{"product_id": 1, "qty": 1}, {"product_id": 9, "qty": 1}])  # GN-009 재고 0
r = c.post(f"/api/orders/{o}/confirm", headers=staff)
assert r.status_code == 409 and stock(1) == s0 and stock(9) == 0
assert c.get(f"/api/orders/{o}", headers=staff).json()["status"] == "PENDING"
# 같은 상품 중복행은 합산되어 검증
o = new([{"product_id": 4, "qty": 5}, {"product_id": 4, "qty": 5}])  # GN-004 재고 8
assert c.post(f"/api/orders/{o}/confirm", headers=staff).status_code == 409 and stock(4) == 8
assert c.post("/api/orders", headers=staff, json={"customer": "t", "items": [{"product_id": 1, "qty": -1}]}).status_code == 422
print("ALL OK")
