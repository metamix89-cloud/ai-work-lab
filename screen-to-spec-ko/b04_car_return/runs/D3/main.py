import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import pricing
import seed

@asynccontextmanager
async def lifespan(_):
    seed.run()
    yield


app = FastAPI(title="부릉부릉렌터카 반납 점검표", lifespan=lifespan)
KST = timezone(timedelta(hours=9))
MAX_PHOTO = 5 * 1024 * 1024
FAILS: dict[str, list[float]] = {}   # 로그인 실패 기록 (프로세스 메모리)


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None, second=0, microsecond=0)


def parse_dt(s: str) -> datetime:
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        raise HTTPException(422, "시각 형식이 올바르지 않습니다")
    return d.replace(tzinfo=None, second=0, microsecond=0)


# ---------- 인증 ----------
def current_user(session: str | None = Cookie(default=None)):
    if session:
        con = db.connect()
        try:
            row = con.execute("SELECT u.id,u.username,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id "
                              "WHERE s.token=?", (session,)).fetchone()
        finally:
            con.close()
        if row:
            return dict(row)
    raise HTTPException(401, "로그인이 필요합니다")


def staff_only(user=Depends(current_user)):
    if user["role"] != "staff":
        raise HTTPException(403, "직원만 사용할 수 있습니다")
    return user


class Login(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=200)


@app.post("/api/login")
def login(body: Login, response: Response):
    key = body.username.lower()
    recent = [t for t in FAILS.get(key, []) if time.time() - t < 300]
    if len(recent) >= 5:
        raise HTTPException(429, "로그인 시도가 너무 많습니다. 5분 뒤 다시 시도하세요")
    con = db.connect()
    try:
        u = con.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
        ok = db.check_pw(body.password, u["pw_hash"] if u else db.hash_pw("x"))
        if not (u and ok):
            FAILS[key] = recent + [time.time()]
            raise HTTPException(401, "아이디 또는 비밀번호가 틀렸습니다")
        FAILS.pop(key, None)
        token = secrets.token_urlsafe(32)
        con.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)", (token, u["id"]))
    finally:
        con.close()
    response.set_cookie("session", token, httponly=True, samesite="strict", max_age=60 * 60 * 12)
    return {"name": u["name"], "role": u["role"]}


@app.post("/api/logout")
def logout(response: Response, session: str | None = Cookie(default=None)):
    if session:
        con = db.connect()
        con.execute("DELETE FROM sessions WHERE token=?", (session,))
        con.close()
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


@app.get("/api/meta")
def meta(user=Depends(current_user)):
    return {"parts": pricing.PARTS, "damage_fee": pricing.DAMAGE_FEE, "fuel_max": pricing.FUEL_MAX}


# ---------- 조회 ----------
def rental_view(con, r, with_customer: bool) -> dict:
    out = {k: r[k] for k in ("id", "start_at", "due_at", "start_fuel", "start_odometer", "status", "plate", "model")}
    if with_customer:
        out["customer"] = r["customer_name"]
    dmg = con.execute("SELECT id,phase,part,grade,photo_id,pre_existing,fee,note FROM rental_damages "
                      "WHERE rental_id=? ORDER BY id", (r["id"],)).fetchall()
    out["checkout_damages"] = [dict(d) for d in dmg if d["phase"] == "checkout"]
    ret = con.execute("SELECT * FROM returns WHERE rental_id=?", (r["id"],)).fetchone()
    if ret:
        out["return"] = {k: ret[k] for k in ret.keys() if k != "staff_id"}
        out["return"]["damages"] = [dict(d) for d in dmg if d["phase"] == "return"]
    return out


RENTAL_SQL = ("SELECT r.*, c.plate, c.model, u.name AS customer_name FROM rentals r "
              "JOIN cars c ON c.id=r.car_id JOIN users u ON u.id=r.customer_id ")


@app.get("/api/rentals")
def list_rentals(user=Depends(current_user)):
    """직원: 전체. 고객: 본인 대여 건만."""
    con = db.connect()
    try:
        if user["role"] == "staff":
            rows = con.execute(RENTAL_SQL + "ORDER BY r.status, r.due_at").fetchall()
        else:
            rows = con.execute(RENTAL_SQL + "WHERE r.customer_id=? ORDER BY r.start_at DESC", (user["id"],)).fetchall()
        return [rental_view(con, r, user["role"] == "staff") for r in rows]
    finally:
        con.close()


def load_rental(con, rental_id: int, user):
    r = con.execute(RENTAL_SQL + "WHERE r.id=?", (rental_id,)).fetchone()
    # 남의 대여 건은 존재 여부도 알려 주지 않는다
    if not r or (user["role"] != "staff" and r["customer_id"] != user["id"]):
        raise HTTPException(404, "대여 건을 찾을 수 없습니다")
    return r


@app.get("/api/rentals/{rental_id}")
def get_rental(rental_id: int, user=Depends(current_user)):
    con = db.connect()
    try:
        return rental_view(con, load_rental(con, rental_id, user), user["role"] == "staff")
    finally:
        con.close()


# ---------- 사진 ----------
def sniff_image(b: bytes) -> tuple[str, str] | None:
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ".jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", ".gif"
    return None


@app.post("/api/photos")
async def upload_photo(file: UploadFile = File(...), user=Depends(staff_only)):
    data = await file.read(MAX_PHOTO + 1)
    if not data:
        raise HTTPException(422, "빈 파일입니다")
    if len(data) > MAX_PHOTO:
        raise HTTPException(413, "사진은 5MB 이하여야 합니다")
    kind = sniff_image(data)
    if not kind:
        raise HTTPException(415, "JPEG/PNG/WEBP/GIF 사진만 올릴 수 있습니다")
    name = uuid.uuid4().hex + kind[1]
    (db.UPLOAD_DIR / name).write_bytes(data)
    con = db.connect()
    try:
        pid = con.execute("INSERT INTO photos(filename,mime,uploaded_by) VALUES(?,?,?)",
                          (name, kind[0], user["id"])).lastrowid
    finally:
        con.close()
    return {"photo_id": pid}


@app.get("/api/photos/{photo_id}")
def get_photo(photo_id: int, user=Depends(current_user)):
    con = db.connect()
    try:
        p = con.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        allowed = False
        if p:
            if user["role"] == "staff":
                allowed = True
            else:  # 고객은 본인 대여 건에 붙은 사진만
                allowed = con.execute("SELECT 1 FROM rental_damages d JOIN rentals r ON r.id=d.rental_id "
                                      "WHERE d.photo_id=? AND r.customer_id=?", (photo_id, user["id"])).fetchone() is not None
    finally:
        con.close()
    if not allowed:
        raise HTTPException(404, "사진을 찾을 수 없습니다")
    return FileResponse(db.UPLOAD_DIR / p["filename"], media_type=p["mime"],
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox",
                                 "Cache-Control": "private, max-age=300"})


# ---------- 반납 ----------
class DamageIn(BaseModel):
    part: str
    grade: str
    photo_id: int | None = None


class ReturnIn(BaseModel):
    returned_at: str
    fuel: int
    odometer: int
    damages: list[DamageIn] = Field(default_factory=list, max_length=30)


def prepare(con, rental, body: ReturnIn) -> dict:
    if rental["status"] != "active":
        raise HTTPException(409, "이미 반납 처리된 대여 건입니다")
    returned = parse_dt(body.returned_at)
    if returned < parse_dt(rental["start_at"]):
        raise HTTPException(422, "반납 시각이 대여 시작보다 빠릅니다")
    if returned > now_kst() + timedelta(minutes=10):
        raise HTTPException(422, "반납 시각이 미래입니다")
    if body.odometer < rental["start_odometer"]:
        raise HTTPException(422, "주행거리가 대여 시작 때보다 작습니다")
    if not 0 <= body.fuel <= pricing.FUEL_MAX:
        raise HTTPException(422, "연료는 0~8칸입니다")
    ids = [d.photo_id for d in body.damages if d.photo_id]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "같은 사진을 여러 흠집에 쓸 수 없습니다")
    for pid in ids:
        ph = con.execute("SELECT attached FROM photos WHERE id=?", (pid,)).fetchone()
        if not ph or ph["attached"]:
            raise HTTPException(422, f"사용할 수 없는 사진입니다 (id {pid})")
    pre = [dict(r) for r in con.execute("SELECT part,grade FROM rental_damages WHERE rental_id=? AND phase='checkout'",
                                        (rental["id"],))]
    try:
        calc = pricing.compute(parse_dt(rental["due_at"]), returned, rental["start_fuel"], body.fuel,
                               pre, [d.model_dump() for d in body.damages])
    except ValueError as e:
        raise HTTPException(422, str(e))
    calc["returned_at"] = returned.strftime("%Y-%m-%dT%H:%M")
    return calc


@app.post("/api/rentals/{rental_id}/return/preview")
def preview(rental_id: int, body: ReturnIn, user=Depends(staff_only)):
    con = db.connect()
    try:
        return prepare(con, load_rental(con, rental_id, user), body)
    finally:
        con.close()


@app.post("/api/rentals/{rental_id}/return")
def do_return(rental_id: int, body: ReturnIn, user=Depends(staff_only)):
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")  # 동시 반납 방지
        try:
            r = load_rental(con, rental_id, user)
            calc = prepare(con, r, body)
            con.execute("INSERT INTO returns VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (rental_id, calc["returned_at"], body.fuel, body.odometer, calc["late_minutes"], calc["late_fee"],
                         calc["fuel_short"], calc["fuel_fee"], calc["damage_fee"], calc["total"], user["id"]))
            for d in calc["damages"]:
                con.execute("INSERT INTO rental_damages(rental_id,phase,part,grade,photo_id,pre_existing,fee,note) "
                            "VALUES(?,'return',?,?,?,?,?,?)",
                            (rental_id, d["part"], d["grade"], d["photo_id"], int(d["pre_existing"]), d["fee"], d["note"]))
                con.execute("UPDATE photos SET attached=1 WHERE id=?", (d["photo_id"],))
            con.execute("UPDATE rentals SET status='returned' WHERE id=?", (rental_id,))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        return rental_view(con, load_rental(con, rental_id, user), True)
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(db.BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=db.BASE / "static"), name="static")
