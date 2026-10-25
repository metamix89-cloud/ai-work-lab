import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import calc, db
from .security import new_token, sniff_image, token_hash, verify_password

KST = timezone(timedelta(hours=9))
SESSION_HOURS = 12
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTOS_PER_RENTAL = 30
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

@asynccontextmanager
async def lifespan(_):
    db.init_db()
    from .seed import seed_if_empty
    seed_if_empty()
    yield


app = FastAPI(title="부릉부릉렌터카 반납 점검표", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'")
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None, microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------- auth
_fails: dict[str, list[float]] = {}


def current_user(request: Request, con=Depends(db.get_con)):
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(401, "로그인이 필요합니다")
    row = con.execute(
        "SELECT u.id, u.username, u.name, u.role, s.created_at FROM sessions s "
        "JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (token_hash(token),)).fetchone()
    if not row or now() - parse(row["created_at"]) > timedelta(hours=SESSION_HOURS):
        raise HTTPException(401, "로그인이 필요합니다")
    return dict(row)


def staff_only(user=Depends(current_user)):
    if user["role"] != "staff":
        raise HTTPException(403, "직원만 사용할 수 있습니다")
    return user


class LoginIn(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=200)


@app.post("/api/login")
def login(body: LoginIn, response: Response, con=Depends(db.get_con)):
    recent = [t for t in _fails.get(body.username, []) if time.time() - t < 60]
    if len(recent) >= 5:
        raise HTTPException(429, "로그인 시도가 너무 많습니다. 1분 뒤 다시 시도하세요")
    u = con.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if not u or not verify_password(body.password, u["password_hash"]):
        _fails[body.username] = recent + [time.time()]
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    _fails.pop(body.username, None)
    token = new_token()
    con.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), u["id"], iso(now())))
    response.set_cookie("session", token, httponly=True, samesite="lax",
                        max_age=SESSION_HOURS * 3600)
    return {"name": u["name"], "role": u["role"]}


@app.post("/api/logout")
def logout(request: Request, response: Response, con=Depends(db.get_con)):
    token = request.cookies.get("session")
    if token:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"name": user["name"], "role": user["role"]}


@app.get("/api/config")
def config(user=Depends(current_user)):
    return {
        "parts": {k: {"name": v[0], "factor": v[1]} for k, v in calc.PARTS.items()},
        "grades": {k: {"name": calc.GRADES[k], "fee": calc.GRADE_FEE[k]} for k in calc.GRADES},
        "grace_minutes": calc.GRACE_MINUTES, "fuel_units": calc.FUEL_UNITS,
        "fuel_price_per_liter": calc.FUEL_PRICE_PER_LITER,
    }


# ---------------------------------------------------------------- rentals
BASE_SQL = (
    "SELECT r.*, v.plate, v.model, v.daily_rate, v.tank_liters, c.name AS customer_name "
    "FROM rentals r JOIN vehicles v ON v.id=r.vehicle_id JOIN users c ON c.id=r.customer_id ")


def load_rental(con, rental_id: int, user: dict) -> dict:
    """고객은 본인 대여 건만 조회 가능 — 남의 건은 존재 여부도 숨기려고 404."""
    sql = BASE_SQL + "WHERE r.id=?"
    args = [rental_id]
    if user["role"] != "staff":
        sql += " AND r.customer_id=?"
        args.append(user["id"])
    row = con.execute(sql, args).fetchone()
    if not row:
        raise HTTPException(404, "대여 건을 찾을 수 없습니다")
    return dict(row)


def detail(con, r: dict, user: dict) -> dict:
    dmg = [dict(d) for d in con.execute(
        "SELECT id, phase, part, grade, note, photo_id, status, prior_grade, fee "
        "FROM damages WHERE rental_id=? ORDER BY id", (r["id"],))]
    inv = con.execute("SELECT * FROM invoices WHERE rental_id=?", (r["id"],)).fetchone()
    out = {k: r[k] for k in (
        "id", "plate", "model", "daily_rate", "customer_name", "start_at", "due_at",
        "start_fuel", "start_odo", "status", "returned_at", "return_fuel", "return_odo")}
    out["pickup_damages"] = [d for d in dmg if d["phase"] == "pickup"]
    out["return_damages"] = [d for d in dmg if d["phase"] == "return"]
    out["invoice"] = dict(inv) if inv else None
    return out


@app.get("/api/rentals")
def list_rentals(status: str | None = None, user=Depends(current_user), con=Depends(db.get_con)):
    sql, args = BASE_SQL + "WHERE 1=1", []
    if user["role"] != "staff":           # 고객: 본인 건만
        sql += " AND r.customer_id=?"
        args.append(user["id"])
    if status in ("rented", "returned"):
        sql += " AND r.status=?"
        args.append(status)
    sql += " ORDER BY r.status='rented' DESC, r.due_at DESC"
    out = []
    for r in con.execute(sql, args).fetchall():
        d = detail(con, dict(r), user)
        out.append(d)
    return out


@app.get("/api/rentals/{rental_id}")
def get_rental(rental_id: int, user=Depends(current_user), con=Depends(db.get_con)):
    return detail(con, load_rental(con, rental_id, user), user)


# ---------------------------------------------------------------- photos
@app.post("/api/rentals/{rental_id}/photos")
async def upload_photo(rental_id: int, file: UploadFile = File(...),
                       user=Depends(staff_only), con=Depends(db.get_con)):
    r = load_rental(con, rental_id, user)
    if r["status"] != "rented":
        raise HTTPException(409, "이미 반납 완료된 건입니다")
    if con.execute("SELECT COUNT(*) FROM photos WHERE rental_id=?", (rental_id,)).fetchone()[0] \
            >= MAX_PHOTOS_PER_RENTAL:
        raise HTTPException(400, "사진 개수 한도를 넘었습니다")
    data = await file.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "사진은 5MB 이하만 가능합니다")
    ctype = sniff_image(data)
    if not ctype:
        raise HTTPException(400, "JPEG/PNG/WEBP 이미지만 업로드할 수 있습니다")
    name = uuid.uuid4().hex                      # 사용자 제공 파일명은 쓰지 않음
    with open(os.path.join(db.UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    cur = con.execute("INSERT INTO photos(rental_id, filename, content_type, uploaded_by) "
                      "VALUES(?,?,?,?)", (rental_id, name, ctype, user["id"]))
    return {"photo_id": cur.lastrowid}


@app.get("/api/photos/{photo_id}")
def get_photo(photo_id: int, user=Depends(current_user), con=Depends(db.get_con)):
    p = con.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not p:
        raise HTTPException(404, "사진을 찾을 수 없습니다")
    load_rental(con, p["rental_id"], user)       # 고객이면 본인 대여 건 사진만 통과
    return FileResponse(os.path.join(db.UPLOAD_DIR, p["filename"]), media_type=p["content_type"],
                        headers={"Content-Disposition": "inline"})


# ---------------------------------------------------------------- return inspection
class DamageIn(BaseModel):
    part: str
    grade: int
    note: str = Field(default="", max_length=200)
    photo_id: int | None = None


class ReturnIn(BaseModel):
    returned_at: datetime | None = None
    return_fuel: int = Field(ge=0, le=calc.FUEL_UNITS)
    return_odo: int = Field(ge=0, le=9_999_999)
    damages: list[DamageIn] = Field(default_factory=list, max_length=len(calc.PARTS))


def evaluate(con, r: dict, body: ReturnIn, require_photo: bool):
    if r["status"] != "rented":
        raise HTTPException(409, "이미 반납 처리된 건입니다")
    ret = body.returned_at or now()
    if ret.tzinfo:
        ret = ret.astimezone(KST).replace(tzinfo=None)
    ret = ret.replace(second=0, microsecond=0)
    if ret < parse(r["start_at"]):
        raise HTTPException(400, "반납 시각이 대여 시작 시각보다 빠릅니다")
    if ret > now() + timedelta(minutes=10):
        raise HTTPException(400, "반납 시각이 미래입니다")
    if body.return_odo < r["start_odo"]:
        raise HTTPException(400, f"주행거리는 대여 시작({r['start_odo']}km) 이상이어야 합니다")
    if body.return_fuel > calc.FUEL_UNITS:
        raise HTTPException(400, "연료 값이 올바르지 않습니다")
    parts, photos = set(), set()
    for d in body.damages:
        if d.part not in calc.PARTS:
            raise HTTPException(400, f"알 수 없는 부위: {d.part}")
        if d.grade not in calc.GRADES:
            raise HTTPException(400, "흠집 등급은 1~3 이어야 합니다")
        if d.part in parts:
            raise HTTPException(400, f"같은 부위가 중복 입력됨: {calc.PARTS[d.part][0]}")
        parts.add(d.part)
        if d.photo_id is not None:
            if d.photo_id in photos or not con.execute(
                    "SELECT 1 FROM photos WHERE id=? AND rental_id=?",
                    (d.photo_id, r["id"])).fetchone():
                raise HTTPException(400, "사진이 올바르지 않습니다")
            photos.add(d.photo_id)
    pickup = [dict(x) for x in con.execute(
        "SELECT part, grade FROM damages WHERE rental_id=? AND phase='pickup'", (r["id"],))]
    result = calc.compute(
        daily_rate=r["daily_rate"], tank_liters=r["tank_liters"], due_at=parse(r["due_at"]),
        start_fuel=r["start_fuel"], returned_at=ret, return_fuel=body.return_fuel,
        pickup_damages=pickup,
        found_damages=[{"part": d.part, "grade": d.grade, "note": d.note, "photo_id": d.photo_id}
                       for d in body.damages])
    if require_photo:
        for it in result["damage_items"]:
            if it["fee"] > 0 and it["photo_id"] is None:
                raise HTTPException(400, f"청구되는 흠집({calc.PARTS[it['part']][0]})에는 사진이 필요합니다")
    return ret, result


@app.post("/api/rentals/{rental_id}/preview")
def preview(rental_id: int, body: ReturnIn, user=Depends(staff_only), con=Depends(db.get_con)):
    r = load_rental(con, rental_id, user)
    ret, result = evaluate(con, r, body, require_photo=False)
    return {"returned_at": iso(ret), **result}


@app.post("/api/rentals/{rental_id}/return")
def finish_return(rental_id: int, body: ReturnIn, user=Depends(staff_only),
                  con=Depends(db.get_con)):
    r = load_rental(con, rental_id, user)
    ret, res = evaluate(con, r, body, require_photo=True)
    # 조건부 UPDATE 로 중복 반납(이중 청구)을 원자적으로 차단
    cur = con.execute(
        "UPDATE rentals SET status='returned', returned_at=?, return_fuel=?, return_odo=?, "
        "staff_id=? WHERE id=? AND status='rented'",
        (iso(ret), body.return_fuel, body.return_odo, user["id"], rental_id))
    if cur.rowcount != 1:
        raise HTTPException(409, "이미 반납 처리된 건입니다")
    for it in res["damage_items"]:
        con.execute(
            "INSERT INTO damages(rental_id, phase, part, grade, note, photo_id, status, "
            "prior_grade, fee) VALUES(?,?,?,?,?,?,?,?,?)",
            (rental_id, "return", it["part"], it["grade"], it["note"], it["photo_id"],
             it["status"], it["prior_grade"], it["fee"]))
    con.execute("UPDATE vehicles SET odometer=? WHERE id=?", (body.return_odo, r["vehicle_id"]))
    con.execute(
        "INSERT INTO invoices(rental_id, late_minutes, late_fee, fuel_short_units, fuel_fee, "
        "damage_fee, total, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (rental_id, res["late_minutes"], res["late_fee"], res["fuel_short_units"],
         res["fuel_fee"], res["damage_fee"], res["total"], iso(now())))
    return detail(con, load_rental(con, rental_id, user), user)


# ---------------------------------------------------------------- static
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
