import os, tempfile
os.environ["KORREUK_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from fastapi.testclient import TestClient
import main

c = TestClient(main.app)
H = {"X-Admin-Pin": "1234"}
print(c.get("/api/summary").json()["counts"])
print(c.get("/").status_code)
r = c.post("/api/ship", json={"product_id": 1, "qty": 150}); print(r.status_code, r.json())
print(c.post("/api/ship", json={"product_id": 1, "qty": 9999}).json())
lots = c.get("/api/lots").json()
exp = [l for l in lots if l["status"] == "expired"]
print("no pin:", c.post(f"/api/lots/{exp[0]['id']}/dispose").status_code)
print("admin:", c.post(f"/api/lots/{exp[0]['id']}/dispose", headers=H).json())
ok = [l for l in lots if l["status"] == "ok"][0]
print("non-expired dispose:", c.post(f"/api/lots/{ok['id']}/dispose", headers=H).status_code)
print(c.get("/api/movements").json()[:4])
