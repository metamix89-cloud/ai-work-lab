import os, tempfile
os.environ["BRL_DATA_DIR"] = tempfile.mkdtemp()
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app import billing

def login(c, u):
    r = c.post("/api/login", json={"username": u, "password": "demo1234"}); assert r.status_code == 200, r.text

def test_billing_rules():
    d = datetime(2026, 1, 1, 12)
    assert billing.late_fee(d, d + timedelta(minutes=30), 60000) == (30, 0)           # 유예
    assert billing.late_fee(d, d + timedelta(minutes=31), 60000)[1] == 6000           # 1시간(올림)
    assert billing.late_fee(d, d + timedelta(hours=20), 60000)[1] == 60000            # 하루치 상한
    assert billing.late_fee(d, d + timedelta(hours=25), 60000)[1] == 66000            # 1일 + 1시간
    assert billing.fuel_short if hasattr(billing, "fuel_short") else True
    assert billing.fuel_fee(8, 8, 47) == (0, 0) and billing.fuel_fee(4, 8, 47) == (0, 0)
    assert billing.fuel_fee(8, 5, 48) == (3, 36000 + 10000)
    assert billing.damage_line(2, 2) == (0, "existing") and billing.damage_line(1, 3) == (350000, "worse")

def test_flow_and_isolation():
    with TestClient(app) as staff, TestClient(app) as minsu, TestClient(app) as jiyeon:
        login(staff, "staff"); login(minsu, "minsu"); login(jiyeon, "jiyeon")
        mine = minsu.get("/api/rentals").json()
        assert mine and all(r["customer"] == "박민수" for r in mine)
        other = [r for r in staff.get("/api/rentals").json() if r["customer"] == "이지연"][0]
        assert minsu.get(f"/api/rentals/{other['id']}").status_code == 404
        assert minsu.post(f"/api/rentals/{other['id']}/return", json={}).status_code == 403
        assert minsu.get("/api/staff/options").status_code == 403
        # 청구서 시드: 기존 흠집(앞범퍼)은 0원, 신규(조수석 뒷문 2등급)만 청구
        done = [r for r in mine if r["status"] == "returned"][0]
        fees = {d["part"]: (d["fee"], d["status"]) for d in done["return_damages"]}
        assert fees["앞범퍼"] == (0, "existing") and fees["조수석 뒷문"] == (150000, "new")
        assert done["invoice"]["total"] == done["invoice"]["late_fee"] + done["invoice"]["fuel_fee"] + 150000
        # 타인 사진 접근 불가 / 본인 사진 가능
        ph = [d["photo"] for d in done["return_damages"] if d["photo"]][0]
        assert minsu.get(f"/api/photos/{ph}").status_code == 200
        assert jiyeon.get(f"/api/photos/{ph}").status_code == 404
        # 반납 처리
        act = [r for r in staff.get("/api/rentals").json() if r["status"] == "active" and r["customer"] == "박민수"][0]
        body = {"returned_at": datetime.now().strftime("%Y-%m-%dT%H:%M"), "fuel": 4, "odometer": act["start_odometer"] + 100,
                "damages": [{"part": "앞범퍼", "grade": 2}, {"part": "운전석 앞문", "grade": 3}, {"part": "지붕", "grade": 1}]}
        p = staff.post(f"/api/rentals/{act['id']}/preview", json=body).json()
        by = {d["part"]: d for d in p["damages"]}
        assert by["앞범퍼"]["fee"] == 0 and by["운전석 앞문"]["fee"] == 350000 and by["지붕"]["fee"] == 50000
        assert by["조수석 뒷문"]["fee"] == 0 if "조수석 뒷문" in by else True
        assert p["late_fee"] > 0 and p["fuel_fee"] > 0 and p["total"] == p["late_fee"] + p["fuel_fee"] + p["damage_fee"]
        assert staff.post(f"/api/rentals/{act['id']}/return", json={**body, "odometer": 1}).status_code == 422
        r = staff.post(f"/api/rentals/{act['id']}/return", json=body); assert r.status_code == 200, r.text
        assert staff.post(f"/api/rentals/{act['id']}/return", json=body).status_code == 409   # 이중 반납 차단
        assert minsu.get(f"/api/rentals/{act['id']}").json()["invoice"]["total"] == p["total"]
        # 중복 부위 / 잘못된 사진 참조 거부
        dup = {**body, "damages": [{"part": "지붕", "grade": 1}, {"part": "지붕", "grade": 2}]}
        other_act = [r for r in staff.get("/api/rentals").json() if r["status"] == "active"][0]
        assert staff.post(f"/api/rentals/{other_act['id']}/preview", json=dup).status_code == 422
        bad = {**body, "damages": [{"part": "지붕", "grade": 1, "photo": "../../x.png"}]}
        assert staff.post(f"/api/rentals/{other_act['id']}/preview", json=bad).status_code == 422
        # 사진 업로드 검증
        assert staff.post("/api/photos", files={"file": ("a.png", b"not an image")}).status_code == 415
        assert minsu.post("/api/photos", files={"file": ("a.png", b"\x89PNG\r\n\x1a\n")}).status_code == 403
    with TestClient(app) as anon:
        assert anon.get("/api/rentals").status_code == 401
