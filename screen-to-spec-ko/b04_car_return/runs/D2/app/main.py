import json
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, billing, photos, service
from .db import UPLOAD_DIR, init_db
from .seed import seed_if_empty

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_DAMAGES = 20

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_if_empty()
    yield


app = FastAPI(title="부릉부릉렌터카 반납 점검표", lifespan=lifespan)


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: Login, response: Response, conn=Depends(auth.get_conn)):
    user = auth.check_login(conn, body.username, body.password)
    if user is None:
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    token = auth.create_session(conn, user["id"])
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict",
                        max_age=auth.SESSION_HOURS * 3600)
    return {"name": user["name"], "role": user["role"]}


@app.post("/api/logout")
def logout(request: Request, response: Response, conn=Depends(auth.get_conn)):
    token = request.cookies.get(auth.COOKIE)
    if token:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(auth.current_user)):
    return {"name": user["name"], "role": user["role"]}


@app.get("/api/meta")
def meta(user=Depends(auth.current_user)):
    return {"parts": service.PARTS, "grades": billing.GRADE_LABEL, "damage_fees": billing.DAMAGE_FEES,
            "fuel_max": billing.FUEL_MAX}


def _rental_row(r) -> dict:
    return {k: r[k] for k in r.keys()}


_SELECT = ("SELECT r.*, v.plate, v.model, c.name AS customer_name FROM rentals r"
           " JOIN vehicles v ON v.id=r.vehicle_id JOIN users c ON c.id=r.customer_id")


@app.get("/api/rentals")
def list_rentals(user=Depends(auth.current_user), conn=Depends(auth.get_conn)):
    if user["role"] == "staff":
        rows = conn.execute(_SELECT + " ORDER BY (r.status='active') DESC, r.due_at").fetchall()
    else:
        rows = conn.execute(_SELECT + " WHERE r.customer_id=? ORDER BY r.started_at DESC", (user["id"],)).fetchall()
    return [_rental_row(r) for r in rows]


@app.get("/api/rentals/{rental_id}")
def rental_detail(rental_id: int, user=Depends(auth.current_user), conn=Depends(auth.get_conn)):
    r = conn.execute(_SELECT + " WHERE r.id=?", (rental_id,)).fetchone()
    # 고객은 남의 건이 존재하는지조차 알 수 없게 404
    if r is None or (user["role"] == "customer" and r["customer_id"] != user["id"]):
        raise HTTPException(404, "대여 건을 찾을 수 없습니다.")
    out = _rental_row(r)
    out["damages"] = [dict(d) for d in conn.execute(
        "SELECT id,phase,part,grade,note,pre_existing_id,pre_existing,fee FROM damages WHERE rental_id=? ORDER BY id",
        (rental_id,))]
    out["charges"] = [dict(c) for c in conn.execute(
        "SELECT id,kind,description,amount,damage_id FROM charges WHERE rental_id=? ORDER BY id", (rental_id,))]
    return out


@app.get("/api/photos/{damage_id}")
def photo(damage_id: int, user=Depends(auth.current_user), conn=Depends(auth.get_conn)):
    d = conn.execute("SELECT d.photo, r.customer_id FROM damages d JOIN rentals r ON r.id=d.rental_id"
                     " WHERE d.id=?", (damage_id,)).fetchone()
    if d is None or (user["role"] == "customer" and d["customer_id"] != user["id"]):
        raise HTTPException(404, "사진을 찾을 수 없습니다.")
    return FileResponse(UPLOAD_DIR / d["photo"], headers={"X-Content-Type-Options": "nosniff"})


def _int(form, key: str, label: str) -> int:
    try:
        return int(str(form.get(key, "")).strip())
    except ValueError:
        raise service.ReturnError(f"{label}을(를) 숫자로 입력하세요.")


@app.post("/api/rentals/{rental_id}/return")
async def submit_return(rental_id: int, request: Request, staff=Depends(auth.staff_only),
                        conn=Depends(auth.get_conn)):
    """multipart: returned_at, end_fuel, end_odometer, damages(JSON 배열), photo_<n> (n = 배열 인덱스)"""
    saved: list[str] = []
    try:
        form = await request.form()
        returned_at = service.parse_kst(str(form.get("returned_at", "")))
        if returned_at > service.now_kst().replace(second=0, microsecond=0) + timedelta(minutes=5):
            raise service.ReturnError("반납 시각이 미래입니다.")
        end_fuel = _int(form, "end_fuel", "연료")
        end_odo = _int(form, "end_odometer", "주행거리")
        try:
            items = json.loads(str(form.get("damages", "[]")))
            assert isinstance(items, list) and all(isinstance(i, dict) for i in items)
        except (ValueError, AssertionError):
            raise service.ReturnError("흠집 목록 형식이 올바르지 않습니다.")
        if len(items) > MAX_DAMAGES:
            raise service.ReturnError(f"흠집은 최대 {MAX_DAMAGES}건까지 입력할 수 있습니다.")

        damages = []
        for n, it in enumerate(items):
            f = form.get(f"photo_{n}")
            data = await f.read() if hasattr(f, "read") else b""
            if not data:
                raise service.ReturnError(f"{n + 1}번 흠집: 사진이 없는 흠집은 접수할 수 없습니다.")
            try:
                name = photos.save(data)
            except ValueError as e:
                raise service.ReturnError(f"{n + 1}번 흠집: {e}")
            saved.append(name)
            pid = it.get("pre_existing_id")
            if pid is not None and not isinstance(pid, int):
                raise service.ReturnError("흠집 연결 값이 올바르지 않습니다.")
            damages.append({"part": it.get("part"), "grade": it.get("grade"), "photo": name,
                            "note": str(it.get("note") or ""), "pre_existing_id": pid})
        return service.finalize_return(conn, rental_id, staff["id"], returned_at, end_fuel, end_odo, damages)
    except service.ReturnError as e:
        for name in saved:
            photos.delete(name)
        raise HTTPException(e.status, e.message)
    except BaseException:
        for name in saved:
            photos.delete(name)
        raise


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
