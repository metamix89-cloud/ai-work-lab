import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import billing

BASE = Path(__file__).parent
DB_PATH = BASE / "data" / "rental.db"
UPLOAD_DIR = BASE / "data" / "uploads"
MAX_PHOTO = 5 * 1024 * 1024
MAX_DAMAGES = 20
SESSION_HOURS = 12

PARTS = {
    "front_bumper": "앞 범퍼", "rear_bumper": "뒤 범퍼", "hood": "보닛", "trunk": "트렁크",
    "roof": "지붕", "front_left_door": "좌측 앞문", "rear_left_door": "좌측 뒷문",
    "front_right_door": "우측 앞문", "rear_right_door": "우측 뒷문",
    "left_fender": "좌측 펜더", "right_fender": "우측 펜더", "windshield": "앞 유리",
    "rear_window": "뒷 유리", "wheel": "휠/타이어", "mirror": "사이드미러", "interior": "실내",
}
GRADE_LABEL = {"minor": "경미", "major": "중간", "severe": "심각"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('staff','customer')), salt TEXT NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vehicles(
  id INTEGER PRIMARY KEY, plate TEXT UNIQUE NOT NULL, model TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rentals(
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES users(id),
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  pickup_at TEXT NOT NULL, due_at TEXT NOT NULL,
  pickup_fuel INTEGER NOT NULL CHECK(pickup_fuel BETWEEN 0 AND 8), pickup_odometer INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','returned')),
  returned_at TEXT, return_fuel INTEGER CHECK(return_fuel BETWEEN 0 AND 8), return_odometer INTEGER,
  returned_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS damages(
  id INTEGER PRIMARY KEY, rental_id INTEGER NOT NULL REFERENCES rentals(id),
  phase TEXT NOT NULL CHECK(phase IN ('pickup','return')),
  part TEXT NOT NULL, grade TEXT NOT NULL CHECK(grade IN ('minor','major','severe')),
  photo TEXT NOT NULL, pre_existing INTEGER NOT NULL DEFAULT 0,
  matched_pickup_id INTEGER REFERENCES damages(id), charge INTEGER NOT NULL DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS charges(
  rental_id INTEGER PRIMARY KEY REFERENCES rentals(id),
  late_minutes INTEGER NOT NULL, late_fee INTEGER NOT NULL, fuel_short INTEGER NOT NULL,
  fuel_fee INTEGER NOT NULL, damage_fee INTEGER NOT NULL, total INTEGER NOT NULL, created_at TEXT NOT NULL);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10,
                          check_same_thread=False)  # 요청마다 연결 1개, 순차 사용
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def get_db():
    con = connect()
    try:
        yield con
    finally:
        con.close()


def hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


@asynccontextmanager
async def lifespan(_):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        import seed
        seed.run(con)
    con.close()
    yield


app = FastAPI(title="부릉부릉렌터카 반납 점검표", lifespan=lifespan)


# ---------- 인증 ----------
def current_user(session: str | None = Cookie(default=None), db=Depends(get_db)) -> sqlite3.Row:
    row = None
    if session:
        row = db.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>?",
            (session, datetime.now().isoformat())).fetchone()
    if not row:
        raise HTTPException(401, "로그인이 필요합니다")
    return row


def staff_only(user=Depends(current_user)):
    if user["role"] != "staff":
        raise HTTPException(403, "직원만 사용할 수 있습니다")
    return user


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: Login, response: Response, db=Depends(get_db)):
    u = db.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    # 사용자 유무와 관계없이 같은 해시 비용을 쓴다
    salt = u["salt"] if u else "00" * 16
    ok = hmac.compare_digest(hash_pw(body.password, salt), u["pw_hash"] if u else "x")
    if not (u and ok):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires_at<?", (datetime.now().isoformat(),))
    db.execute("INSERT INTO sessions VALUES(?,?,?)",
               (token, u["id"], (datetime.now() + timedelta(hours=SESSION_HOURS)).isoformat()))
    response.set_cookie("session", token, httponly=True, samesite="strict", max_age=SESSION_HOURS * 3600)
    return {"name": u["name"], "role": u["role"]}


@app.post("/api/logout")
def logout(response: Response, session: str | None = Cookie(default=None), db=Depends(get_db)):
    if session:
        db.execute("DELETE FROM sessions WHERE token=?", (session,))
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"name": user["name"], "role": user["role"]}


@app.get("/api/meta")
def meta(user=Depends(current_user)):
    return {
        "parts": PARTS, "grades": GRADE_LABEL, "damage_price": billing.DAMAGE_PRICE,
        "fuel_max": billing.FUEL_MAX,
    }


# ---------- 조회 ----------
RENTAL_SQL = """
SELECT r.*, v.plate, v.model, u.name AS customer_name, c.late_minutes, c.late_fee, c.fuel_short,
       c.fuel_fee, c.damage_fee, c.total
FROM rentals r JOIN vehicles v ON v.id=r.vehicle_id JOIN users u ON u.id=r.customer_id
LEFT JOIN charges c ON c.rental_id=r.id
"""


def rental_for(db, user, rental_id: int):
    q = RENTAL_SQL + " WHERE r.id=?"
    args = [rental_id]
    if user["role"] == "customer":  # 고객은 자기 건만
        q += " AND r.customer_id=?"
        args.append(user["id"])
    row = db.execute(q, args).fetchone()
    if not row:
        raise HTTPException(404, "대여 건을 찾을 수 없습니다")
    return row


@app.get("/api/rentals")
def list_rentals(user=Depends(current_user), db=Depends(get_db)):
    if user["role"] == "staff":
        rows = db.execute(RENTAL_SQL + " ORDER BY r.status='active' DESC, r.due_at DESC").fetchall()
    else:
        rows = db.execute(RENTAL_SQL + " WHERE r.customer_id=? ORDER BY r.pickup_at DESC", (user["id"],)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/rentals/{rental_id}")
def rental_detail(rental_id: int, user=Depends(current_user), db=Depends(get_db)):
    r = dict(rental_for(db, user, rental_id))
    r["damages"] = [dict(d) for d in db.execute(
        "SELECT id, phase, part, grade, pre_existing, matched_pickup_id, charge, note FROM damages "
        "WHERE rental_id=? ORDER BY phase DESC, id", (rental_id,))]
    return r


@app.get("/api/photos/{damage_id}")
def photo(damage_id: int, user=Depends(current_user), db=Depends(get_db)):
    d = db.execute("SELECT rental_id, photo FROM damages WHERE id=?", (damage_id,)).fetchone()
    if not d:
        raise HTTPException(404)
    rental_for(db, user, d["rental_id"])  # 접근 권한 검사
    path = UPLOAD_DIR / Path(d["photo"]).name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private"})


# ---------- 반납 처리 ----------
def sniff_ext(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def bill_json(b: billing.Bill) -> dict:
    return {
        "late_minutes": b.late_minutes, "late_fee": b.late_fee, "fuel_short": b.fuel_short,
        "fuel_fee": b.fuel_fee, "damage_fee": b.damage_fee, "total": b.total,
        "damages": [d.__dict__ for d in b.damages],
    }


@app.post("/api/rentals/{rental_id}/return")
async def return_rental(
    rental_id: int,
    returned_at: str = Form(...),
    fuel: int = Form(...),
    odometer: int = Form(...),
    damages: str = Form("[]"),
    dry_run: bool = Form(False),
    photos: list[UploadFile] = File(default=[]),
    user=Depends(staff_only),
    db=Depends(get_db),
):
    r = rental_for(db, user, rental_id)
    if r["status"] != "active":
        raise HTTPException(409, "이미 반납 처리된 건입니다")
    try:
        ret_dt = datetime.fromisoformat(returned_at)
        if ret_dt.tzinfo:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "반납 시각 형식이 올바르지 않습니다")
    if ret_dt < datetime.fromisoformat(r["pickup_at"]):
        raise HTTPException(400, "반납 시각이 대여 시각보다 빠릅니다")
    if not 0 <= fuel <= billing.FUEL_MAX:
        raise HTTPException(400, f"연료는 0~{billing.FUEL_MAX}칸이어야 합니다")
    if odometer < r["pickup_odometer"]:
        raise HTTPException(400, f"주행거리는 대여 때({r['pickup_odometer']}km)보다 작을 수 없습니다")
    try:
        items = json.loads(damages)
        assert isinstance(items, list) and len(items) <= MAX_DAMAGES
        for it in items:
            assert isinstance(it, dict)
    except (ValueError, AssertionError):
        raise HTTPException(400, "흠집 목록 형식이 올바르지 않습니다")

    # 흠집 입력 검증: 부위·등급 유효, 사진 필수
    photo_data: list[tuple[bytes, str]] = []
    for n, it in enumerate(items, 1):
        if it.get("part") not in PARTS or it.get("grade") not in billing.DAMAGE_PRICE:
            raise HTTPException(400, f"흠집 {n}: 부위 또는 등급이 올바르지 않습니다")
        idx = it.get("photo")
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(photos):
            raise HTTPException(400, f"흠집 {n}({PARTS[it['part']]}): 사진이 없는 흠집은 받을 수 없습니다")
        data = await photos[idx].read(MAX_PHOTO + 1)
        if not data or len(data) > MAX_PHOTO:
            raise HTTPException(400, f"흠집 {n}: 사진은 비어 있지 않고 5MB 이하여야 합니다")
        ext = sniff_ext(data)
        if not ext:
            raise HTTPException(400, f"흠집 {n}: JPG/PNG/WEBP 이미지만 가능합니다")
        photo_data.append((data, ext))

    pickup = [dict(d) for d in db.execute(
        "SELECT id, part, grade FROM damages WHERE rental_id=? AND phase='pickup'", (rental_id,))]
    bill = billing.compute_bill(
        datetime.fromisoformat(r["due_at"]), ret_dt, r["pickup_fuel"], fuel, pickup,
        [{"part": it["part"], "grade": it["grade"]} for it in items])
    if dry_run:
        return {"saved": False, **bill_json(bill)}

    saved: list[Path] = []
    try:
        db.execute("BEGIN IMMEDIATE")
        cur = db.execute(
            "UPDATE rentals SET status='returned', returned_at=?, return_fuel=?, return_odometer=?, returned_by=? "
            "WHERE id=? AND status='active'", (ret_dt.isoformat(timespec="minutes"), fuel, odometer, user["id"], rental_id))
        if cur.rowcount != 1:
            raise HTTPException(409, "이미 반납 처리된 건입니다")
        for res, (data, ext) in zip(bill.damages, photo_data):
            name = f"{secrets.token_hex(16)}.{ext}"
            path = UPLOAD_DIR / name
            path.write_bytes(data)
            saved.append(path)
            db.execute(
                "INSERT INTO damages(rental_id,phase,part,grade,photo,pre_existing,matched_pickup_id,charge,note) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (rental_id, "return", res.part, res.grade, name, int(res.pre_existing),
                 res.matched_pickup_id, res.charge, res.note))
        db.execute(
            "INSERT INTO charges VALUES(?,?,?,?,?,?,?,?)",
            (rental_id, bill.late_minutes, bill.late_fee, bill.fuel_short, bill.fuel_fee,
             bill.damage_fee, bill.total, datetime.now().isoformat(timespec="seconds")))
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        for p in saved:
            p.unlink(missing_ok=True)
        raise
    return {"saved": True, **bill_json(bill)}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
