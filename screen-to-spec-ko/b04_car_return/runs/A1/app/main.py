import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import billing, service
from .db import UPLOAD_DIR, check_pw, connect, init_db
from .seed import seed_if_empty

SESSION_HOURS = 12
MAX_PHOTO = 5 * 1024 * 1024
PHOTO_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")
STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="부릉부릉렌터카 반납 점검표")


@app.on_event("startup")
def _startup():
    db = init_db()
    seed_if_empty(db)
    db.close()


@app.exception_handler(service.RuleError)
async def _rule_error(_, e: service.RuleError):
    return JSONResponse({"detail": e.msg}, status_code=e.status)


def get_db():
    db = connect()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get("sid")
    row = token and db.execute(
        "SELECT u.id, u.username, u.name, u.role, s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id"
        " WHERE s.token=?", (token,)).fetchone()
    if not row or row["expires_at"] < datetime.now().isoformat():
        raise HTTPException(401, "로그인이 필요합니다.")
    return dict(row)


def staff_only(user=Depends(current_user)):
    if user["role"] != "staff":
        raise HTTPException(403, "직원만 사용할 수 있습니다.")
    return user


# ---------- 인증 ----------
class LoginIn(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=100)


@app.post("/api/login")
def login(body: LoginIn, response: Response, db=Depends(get_db)):
    u = db.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    # 사용자가 없어도 해시 연산을 수행해 응답 시간 차이로 계정 존재 여부가 드러나지 않게 한다.
    ok = check_pw(body.password, u["pw_salt"] if u else "00" * 16, u["pw_hash"] if u else "")
    if not u or not ok:
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(),))
    db.execute("INSERT INTO sessions VALUES (?,?,?)",
               (token, u["id"], (datetime.now() + timedelta(hours=SESSION_HOURS)).isoformat()))
    response.set_cookie("sid", token, httponly=True, samesite="strict", max_age=SESSION_HOURS * 3600)
    return {"name": u["name"], "role": u["role"]}


@app.post("/api/logout")
def logout(request: Request, response: Response, db=Depends(get_db)):
    db.execute("DELETE FROM sessions WHERE token=?", (request.cookies.get("sid"),))
    response.delete_cookie("sid")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"name": user["name"], "role": user["role"]}


@app.get("/api/meta")
def meta(user=Depends(current_user)):
    return {
        "parts": billing.PARTS,
        "grades": {k: {"label": v, "fee": billing.DAMAGE_FEE[k]} for k, v in billing.GRADES.items()},
        "policy": {
            "grace_minutes": billing.GRACE_MINUTES, "late_hourly_percent": int(billing.LATE_HOURLY_RATE * 100),
            "fuel_price_per_l": billing.FUEL_PRICE_PER_L, "fuel_service_fee": billing.FUEL_SERVICE_FEE,
            "fuel_levels": billing.FUEL_LEVELS,
        },
    }


# ---------- 사진 ----------
def _sniff(data: bytes):
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@app.post("/api/photos")
def upload_photo(file: UploadFile = File(...), user=Depends(staff_only)):
    data = file.file.read(MAX_PHOTO + 1)
    if len(data) > MAX_PHOTO:
        raise HTTPException(413, "사진은 5MB 이하여야 합니다.")
    ext = _sniff(data)
    if not ext:
        raise HTTPException(415, "JPG, PNG, WEBP 이미지만 올릴 수 있습니다.")
    name = f"{secrets.token_hex(16)}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    return {"photo": name}


@app.get("/api/photos/{name}")
def get_photo(name: str, user=Depends(current_user), db=Depends(get_db)):
    if not PHOTO_RE.match(name) or not (UPLOAD_DIR / name).is_file():
        raise HTTPException(404)
    if user["role"] != "staff":
        owns = db.execute(
            "SELECT 1 FROM rental_damage d JOIN rentals r ON r.id=d.rental_id WHERE d.photo=? AND r.user_id=?",
            (name, user["id"])).fetchone()
        if not owns:
            raise HTTPException(404)
    return FileResponse(UPLOAD_DIR / name, headers={"X-Content-Type-Options": "nosniff",
                                                    "Cache-Control": "private, max-age=3600"})


# ---------- 대여 ----------
class DamageIn(BaseModel):
    part: str
    grade: int = Field(ge=1, le=3)
    note: str = Field(default="", max_length=200)
    photo: str | None = None


def _validate_photos(damages: list[DamageIn]):
    for d in damages:
        if d.photo is not None and (not PHOTO_RE.match(d.photo) or not (UPLOAD_DIR / d.photo).is_file()):
            raise HTTPException(422, "올바르지 않은 사진 참조입니다.")


class ReturnIn(BaseModel):
    returned_at: str
    fuel: int = Field(ge=0, le=billing.FUEL_LEVELS)
    odometer: int = Field(ge=0, le=9_999_999)
    damages: list[DamageIn] = Field(default_factory=list, max_length=30)


class RentalIn(BaseModel):
    user_id: int
    vehicle_id: int
    due_at: str
    start_fuel: int = Field(ge=0, le=billing.FUEL_LEVELS)
    damages: list[DamageIn] = Field(default_factory=list, max_length=30)


def _rental_dict(db, r, user):
    out = dict(r)
    v = db.execute("SELECT plate, model, tank_liters FROM vehicles WHERE id=?", (r["vehicle_id"],)).fetchone()
    out["vehicle"] = dict(v)
    out["customer"] = db.execute("SELECT name FROM users WHERE id=?", (r["user_id"],)).fetchone()["name"]
    inv = db.execute("SELECT * FROM invoices WHERE rental_id=?", (r["id"],)).fetchone()
    out["invoice"] = dict(inv) if inv else None
    for phase in ("pickup", "return"):
        out[f"{phase}_damages"] = [dict(x) for x in db.execute(
            "SELECT part, grade, note, photo, fee, status FROM rental_damage WHERE rental_id=? AND phase=? ORDER BY id",
            (r["id"], phase))]
    if user["role"] != "staff":
        out.pop("user_id")
    return out


@app.get("/api/rentals")
def list_rentals(user=Depends(current_user), db=Depends(get_db)):
    sql, args = "SELECT * FROM rentals", ()
    if user["role"] != "staff":
        sql, args = sql + " WHERE user_id=?", (user["id"],)   # 고객은 본인 대여 건만
    rows = db.execute(sql + " ORDER BY (status='active') DESC, start_at DESC", args).fetchall()
    return [_rental_dict(db, r, user) for r in rows]


def _get_rental(db, rid, user):
    r = db.execute("SELECT * FROM rentals WHERE id=?", (rid,)).fetchone()
    if not r or (user["role"] != "staff" and r["user_id"] != user["id"]):
        raise HTTPException(404, "대여 건을 찾을 수 없습니다.")   # 타인 건은 존재 여부도 숨긴다
    return r


@app.get("/api/rentals/{rid}")
def get_rental(rid: int, user=Depends(current_user), db=Depends(get_db)):
    return _rental_dict(db, _get_rental(db, rid, user), user)


@app.get("/api/staff/options")
def options(user=Depends(staff_only), db=Depends(get_db)):
    return {
        "customers": [dict(x) for x in db.execute("SELECT id, name, username FROM users WHERE role='customer'")],
        "vehicles": [dict(x) for x in db.execute(
            "SELECT id, plate, model, daily_rate, odometer FROM vehicles"
            " WHERE id NOT IN (SELECT vehicle_id FROM rentals WHERE status='active') ORDER BY plate")],
    }


@app.post("/api/rentals")
def create_rental(body: RentalIn, user=Depends(staff_only), db=Depends(get_db)):
    _validate_photos(body.damages)
    rid = service.start_rental(db, body.user_id, body.vehicle_id, body.due_at, body.start_fuel,
                               [d.model_dump() for d in body.damages])
    return {"id": rid}


@app.post("/api/rentals/{rid}/preview")
def preview_return(rid: int, body: ReturnIn, user=Depends(staff_only), db=Depends(get_db)):
    _validate_photos(body.damages)
    return service.calculate(db, _get_rental(db, rid, user), body.model_dump())


@app.post("/api/rentals/{rid}/return")
def confirm_return(rid: int, body: ReturnIn, user=Depends(staff_only), db=Depends(get_db)):
    _validate_photos(body.damages)
    _get_rental(db, rid, user)
    return service.finish_return(db, rid, body.model_dump(), user["id"])


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
