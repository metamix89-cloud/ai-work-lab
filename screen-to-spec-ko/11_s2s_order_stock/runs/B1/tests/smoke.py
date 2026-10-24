import sys, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
import main
c = TestClient(main.app)
post = lambda o, a, u="u1": c.post(f"/api/orders/{o}/{a}", json={"user": u})
assert c.get("/").status_code == 200
assert post("O-1002", "confirm").status_code == 409 and post("O-1002", "confirm").json()["detail"].startswith("재고가 부족합니다")
assert [p["stock"] for p in c.get("/api/products").json()][:3] == [10, 5, 3]
r = post("O-1001", "confirm"); assert r.status_code == 200 and r.json()["products"][0]["stock"] == 8
assert post("O-1001", "confirm").status_code == 409
assert post("O-1001", "cancel").json()["products"][0]["stock"] == 10
assert post("O-1004", "refund").status_code == 403 and post("O-1004", "refund", "u3").status_code == 200
assert c.post("/api/orders/NOPE/refund").status_code == 400
assert post("NOPE", "confirm").status_code == 404 and post("O-1001", "confirm", "zz").status_code == 404
assert post("O-1007", "refund").status_code == 403
print("ok")
