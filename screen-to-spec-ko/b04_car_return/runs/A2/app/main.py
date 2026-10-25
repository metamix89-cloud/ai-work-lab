import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import billing
from .db import UPLOAD_DIR, connect, verify_pw
from .seed import seed_if_empty

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_PHOTO = 5 * 1024 * 1024
SESSION_HOURS = 12

app = FastAPI(title="부릉부릉렌터카 반납 점검표")
seed_if_empty()


# ---------- 인증 ----------
def db():
    c = connect()
    try:
        yield c
    finally:
        c.close()


def current_user(authorization: str | None = Header(None), c: sqlite3.Connection = Depends(db)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    row = c.execute("SELECT u.id,u.username,u.name,u.role,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id"
                    " WHERE s.token=?", (token,)).fetchone() if token else None
    if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now():
        raise HTTPException(401, "로그인이 필요합니다")
    return dict(row)


def staff_only(user=Depends(current_user)):
    if user["role"] != "staff":
        raise HTTPException(403, "직원만 사용할 수 있습니다")
    return user


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, c: sqlite3.Connection = Depends(db)):
    u = c.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if not u or not verify_pw(body.password, u["password_hash"]):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    token = secrets.token_urlsafe(32)
    exp = (datetime.now() + timedelta(hours=SESSION_HOURS)).isoformat()
    c.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)", (token, u["id"], exp))
    return {"token": token, "name": u["name"], "role": u["role"]}


@app.post("/api/logout")
def logout(authorization: str | None = Header(None), c: sqlite3.Connection = Depends(db)):
    c.execute("DELETE FROM sessions WHERE token=?", ((authorization or "").removeprefix("Bearer ").strip(),))
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {k: user[k] for k in ("name", "role")}


@app.get("/api/meta")
def meta(user=Depends(current_user)):
    return {"parts": billing.PARTS, "grades": [{"grade": g, "label": billing.GRADE_LABEL[g], "fee": f}
                                               for g, f in billing.DAMAGE_FEE.items()],
            "grace_min": billing.GRACE_MIN}


# ---------- 조회 ----------
def rental_row(c, rid, user):
    r = c.execute("SELECT r.*, v.plate, v.model, v.daily_rate, v.tank_l, cu.name AS customer_name"
                  " FROM rentals r JOIN vehicles v ON v.id=r.vehicle_id JOIN users cu ON cu.id=r.customer_id"
                  " WHERE r.id=?", (rid,)).fetchone()
    # 고객은 남의 대여 건이 존재하는지조차 알 수 없게 404
    if not r or (user["role"] == "customer" and r["customer_id"] != user["id"]):
        raise HTTPException(404, "대여 건을 찾을 수 없습니다")
    return r


@app.get("/api/rentals")
def list_rentals(user=Depends(current_user), c: sqlite3.Connection = Depends(db)):
    sql = ("SELECT r.id,r.start_at,r.due_at,r.status,r.total,r.returned_at,v.plate,v.model,cu.name AS customer_name"
           " FROM rentals r JOIN vehicles v ON v.id=r.vehicle_id JOIN users cu ON cu.id=r.customer_id")
    if user["role"] == "customer":
        rows = c.execute(sql + " WHERE r.customer_id=? ORDER BY r.status, r.due_at DESC", (user["id"],))
    else:
        rows = c.execute(sql + " ORDER BY r.status, r.due_at")
    return [dict(r) for r in rows]


@app.get("/api/rentals/{rid}")
def get_rental(rid: int, user=Depends(current_user), c: sqlite3.Connection = Depends(db)):
    r = dict(rental_row(c, rid, user))
    del r["customer_id"]
    r["pre_damages"] = [dict(d) for d in c.execute(
        "SELECT id,part,grade,photo_id FROM damages WHERE rental_id=? AND kind='pre'", (rid,))]
    r["return_damages"] = [dict(d) for d in c.execute(
        "SELECT id,part,grade,photo_id,note FROM damages WHERE rental_id=? AND kind='return'", (rid,))]
    r["charges"] = [dict(x) for x in c.execute(
        "SELECT type,description,amount,damage_id FROM charges WHERE rental_id=? ORDER BY id", (rid,))]
    return r


@app.get("/api/charges")
def my_charges(user=Depends(current_user), c: sqlite3.Connection = Depends(db)):
    """청구 내역 목록 — 고객은 본인 것만, 직원은 전체."""
    sql = ("SELECT r.id AS rental_id, v.model, v.plate, r.returned_at, r.total, cu.name AS customer_name"
           " FROM rentals r JOIN vehicles v ON v.id=r.vehicle_id JOIN users cu ON cu.id=r.customer_id"
           " WHERE r.status='returned'")
    if user["role"] == "customer":
        rows = c.execute(sql + " AND r.customer_id=? ORDER BY r.returned_at DESC", (user["id"],))
    else:
        rows = c.execute(sql + " ORDER BY r.returned_at DESC")
    return [dict(r) for r in rows]


# ---------- 사진 ----------
MAGIC = {b"\xff\xd8\xff": ("jpg", "image/jpeg"), b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
         b"RIFF": ("webp", "image/webp")}


@app.post("/api/uploads")
def upload(file: UploadFile = File(...), user=Depends(staff_only), c: sqlite3.Connection = Depends(db)):
    data = file.file.read(MAX_PHOTO + 1)
    if len(data) > MAX_PHOTO:
        raise HTTPException(413, "사진은 5MB 이하여야 합니다")
    kind = next((v for k, v in MAGIC.items() if data.startswith(k)), None)
    if not kind or (kind[0] == "webp" and data[8:12] != b"WEBP"):
        raise HTTPException(400, "JPG/PNG/WEBP 이미지만 올릴 수 있습니다")
    name = f"{secrets.token_hex(16)}.{kind[0]}"  # 클라이언트 파일명은 쓰지 않음
    (UPLOAD_DIR / name).write_bytes(data)
    uid = c.execute("INSERT INTO uploads(filename,mime,uploaded_by) VALUES(?,?,?)",
                    (name, kind[1], user["id"])).lastrowid
    return {"id": uid}


@app.get("/api/uploads/{uid}")
def get_upload(uid: int, user=Depends(current_user), c: sqlite3.Connection = Depends(db)):
    u = c.execute("SELECT * FROM uploads WHERE id=?", (uid,)).fetchone()
    ok = False
    if u:
        if user["role"] == "staff":
            ok = True
        else:  # 고객: 자기 대여 건에 붙은 사진만
            ok = c.execute("SELECT 1 FROM damages d JOIN rentals r ON r.id=d.rental_id"
                           " WHERE d.photo_id=? AND r.customer_id=?", (uid, user["id"])).fetchone() is not None
    if not ok:
        raise HTTPException(404, "사진을 찾을 수 없습니다")
    return FileResponse(UPLOAD_DIR / u["filename"], media_type=u["mime"],
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


# ---------- 반납 처리 ----------
class DamageIn(BaseModel):
    part: str
    grade: int
    photo_id: int | None = None


class ReturnIn(BaseModel):
    returned_at: datetime
    odometer: int = Field(ge=0)
    fuel: int = Field(ge=0, le=8, description="연료 눈금 (0~8, 8=가득)")
    damages: list[DamageIn] = Field(default_factory=list, max_length=30)


def compute(c, r, body: ReturnIn):
    if body.returned_at.tzinfo:
        raise HTTPException(422, "반납 시각은 시간대 없이 보내 주세요")
    if body.returned_at < datetime.fromisoformat(r["start_at"]):
        raise HTTPException(422, "반납 시각이 대여 시작보다 빠릅니다")
    if body.odometer < r["start_odometer"]:
        raise HTTPException(422, f"주행거리는 대여 시작({r['start_odometer']:,}km)보다 작을 수 없습니다")
    for d in body.damages:
        if d.part not in billing.PARTS or d.grade not in billing.DAMAGE_FEE:
            raise HTTPException(422, "알 수 없는 부위 또는 등급입니다")
        if d.photo_id is not None and not c.execute("SELECT 1 FROM uploads WHERE id=?", (d.photo_id,)).fetchone():
            raise HTTPException(422, "존재하지 않는 사진입니다")
    # 기존 흠집 여부는 클라이언트가 아니라 서버의 대여 시점 기록으로만 판단한다
    pre = [dict(x) for x in c.execute("SELECT part,grade FROM damages WHERE rental_id=? AND kind='pre'", (r["id"],))]
    lines = [billing.late_line(datetime.fromisoformat(r["due_at"]), body.returned_at, r["daily_rate"]),
             billing.fuel_line(r["start_fuel"], body.fuel, r["tank_l"])]
    lines = [l for l in lines if l] + billing.damage_lines([d.model_dump() for d in body.damages], pre)
    return lines, sum(l["amount"] for l in lines)


@app.post("/api/rentals/{rid}/preview")
def preview(rid: int, body: ReturnIn, user=Depends(staff_only), c: sqlite3.Connection = Depends(db)):
    r = rental_row(c, rid, user)
    lines, total = compute(c, r, body)
    return {"lines": lines, "total": total}


@app.post("/api/rentals/{rid}/return")
def do_return(rid: int, body: ReturnIn, user=Depends(staff_only), c: sqlite3.Connection = Depends(db)):
    c.execute("BEGIN IMMEDIATE")  # 중복 제출 방지: 쓰기 락을 잡고 상태를 확인
    try:
        r = rental_row(c, rid, user)
        if r["status"] != "active":
            raise HTTPException(409, "이미 반납 처리된 대여 건입니다")
        lines, total = compute(c, r, body)
        c.execute("UPDATE rentals SET status='returned', returned_at=?, ret_odometer=?, ret_fuel=?, inspected_by=?,"
                  " total=? WHERE id=?", (body.returned_at.isoformat(timespec="minutes"), body.odometer, body.fuel,
                                          user["id"], total, rid))
        for l in lines:
            did = None
            if l["type"] == "damage":
                did = c.execute("INSERT INTO damages(rental_id,kind,part,grade,photo_id,note) VALUES(?,'return',?,?,?,?)",
                                (rid, l["part"], l["grade"], l["photo_id"], l["note"])).lastrowid
            c.execute("INSERT INTO charges(rental_id,type,description,amount,damage_id) VALUES(?,?,?,?,?)",
                      (rid, l["type"], l["description"], l["amount"], did))
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    return {"lines": lines, "total": total}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
