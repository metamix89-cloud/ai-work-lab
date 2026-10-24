import hmac
import os
import secrets
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import service
from .db import connect, tx
from .seed import hash_pw, seed_if_empty

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


@asynccontextmanager
async def lifespan(app):
    seed_if_empty()
    yield


app = FastAPI(title="가나다식품 주문·재고 백오피스", lifespan=lifespan)


@app.exception_handler(service.BizError)
async def biz_error_handler(request, exc: service.BizError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


# ---------- 인증 ----------
def current_user(authorization: Optional[str] = Header(None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")
    conn = connect()
    try:
        row = conn.execute(
            "SELECT u.id, u.username, u.name, u.role FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ?",
            (token,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인하세요.")
    return dict(row)


def admin_only(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "관리자만 수행할 수 있습니다.")
    return user


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn):
    with tx() as conn:
        u = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
        ok = u is not None and hmac.compare_digest(hash_pw(body.password, u["pw_salt"]), u["pw_hash"])
        if not ok:
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessions (token, user_id) VALUES (?,?)", (token, u["id"]))
    return {"token": token, "user": {"username": u["username"], "name": u["name"], "role": u["role"]}}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


# ---------- 조회 ----------
@app.get("/api/products")
def products(user=Depends(current_user)):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY id")]
    finally:
        conn.close()


def _orders_with_items(conn, where="", params=()):
    orders = [dict(r) for r in conn.execute(f"SELECT * FROM orders {where} ORDER BY id DESC", params)]
    if not orders:
        return orders
    by_id = {o["id"]: o for o in orders}
    for o in orders:
        o["items"] = []
    marks = ",".join("?" * len(by_id))
    rows = conn.execute(
        f"SELECT oi.order_id, oi.product_id, oi.qty, oi.unit_price, p.name, p.stock "
        f"FROM order_items oi JOIN products p ON p.id = oi.product_id "
        f"WHERE oi.order_id IN ({marks}) ORDER BY oi.id",
        tuple(by_id),
    )
    for r in rows:
        by_id[r["order_id"]]["items"].append(dict(r))
    return orders


@app.get("/api/orders")
def orders(status: Optional[str] = Query(None), user=Depends(current_user)):
    conn = connect()
    try:
        if status:
            return _orders_with_items(conn, "WHERE status = ?", (status,))
        return _orders_with_items(conn)
    finally:
        conn.close()


@app.get("/api/orders/{order_id}/events")
def order_events(order_id: int, user=Depends(current_user)):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM order_events WHERE order_id = ? ORDER BY id", (order_id,))]
    finally:
        conn.close()


@app.get("/api/movements")
def movements(limit: int = Query(100, ge=1, le=500), user=Depends(current_user)):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT m.*, p.name AS product_name FROM stock_movements m "
            "JOIN products p ON p.id = m.product_id ORDER BY m.id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


# ---------- 주문 처리 ----------
class ItemIn(BaseModel):
    product_id: int
    qty: int = Field(gt=0, le=10000)


class OrderIn(BaseModel):
    customer: str = Field(min_length=1, max_length=50)
    phone: str = Field("", max_length=30)
    address: str = Field("", max_length=200)
    items: List[ItemIn] = Field(min_length=1)


@app.post("/api/orders", status_code=201)
def create_order(body: OrderIn, user=Depends(current_user)):
    oid = service.create_order(body.customer, body.phone, body.address,
                               [(i.product_id, i.qty) for i in body.items], user["username"])
    return {"id": oid}


@app.post("/api/orders/{order_id}/confirm")
def confirm(order_id: int, user=Depends(current_user)):
    service.confirm_order(order_id, user["username"])
    return {"ok": True}


@app.post("/api/orders/{order_id}/ship")
def ship(order_id: int, user=Depends(current_user)):
    service.ship_order(order_id, user["username"])
    return {"ok": True}


class NoteIn(BaseModel):
    note: str = Field("", max_length=200)


@app.post("/api/orders/{order_id}/cancel")
def cancel(order_id: int, body: NoteIn = NoteIn(), user=Depends(current_user)):
    service.cancel_order(order_id, user["username"], body.note)
    return {"ok": True}


class RefundIn(BaseModel):
    note: str = Field("", max_length=200)
    restock: bool = True


@app.post("/api/orders/{order_id}/refund")
def refund(order_id: int, body: RefundIn = RefundIn(), user=Depends(admin_only)):
    service.refund_order(order_id, user["username"], body.restock, body.note)
    return {"ok": True}


# ---------- 재고 조정 (관리자) ----------
class AdjustIn(BaseModel):
    delta: int = Field(ge=-100000, le=100000)
    reason: str = Field("", max_length=100)

    @field_validator("delta")
    @classmethod
    def not_zero(cls, v):
        if v == 0:
            raise ValueError("증감 수량은 0일 수 없습니다.")
        return v


@app.post("/api/products/{product_id}/adjust")
def adjust(product_id: int, body: AdjustIn, user=Depends(admin_only)):
    service.adjust_stock(product_id, body.delta, body.reason, user["username"])
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
