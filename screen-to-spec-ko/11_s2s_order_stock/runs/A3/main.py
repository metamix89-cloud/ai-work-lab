"""가나다식품 주문·재고 백오피스 (FastAPI + SQLite)

재고 규칙
- 주문 확정(PENDING→CONFIRMED): 재고 차감. 부족하면 전체 롤백, 409 반환.
- 출고(CONFIRMED→SHIPPED): 재고 변동 없음 (확정 시점에 이미 차감됨).
- 취소(PENDING/CONFIRMED→CANCELLED): CONFIRMED 였다면 재고 복원. 출고 후에는 취소 불가(환불 사용).
- 환불(SHIPPED→REFUNDED, 관리자 전용): 반품 입고 여부(restock)에 따라 재고 복원.
모든 상태 전이는 `UPDATE ... WHERE status=?` 로 원자적으로 수행해 중복 처리(더블클릭/동시 요청)를 막고,
재고는 `UPDATE ... WHERE stock>=?` + CHECK(stock>=0) 로 음수를 이중 차단한다.
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.environ.get("GANADA_DB", str(BASE / "ganada.db"))

app = FastAPI(title="가나다식품 주문·재고 백오피스")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('staff','admin')), pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>=0),
  stock INTEGER NOT NULL CHECK(stock>=0), safety_stock INTEGER NOT NULL DEFAULT 10);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, customer TEXT NOT NULL, phone TEXT, address TEXT,
  status TEXT NOT NULL CHECK(status IN ('PENDING','CONFIRMED','SHIPPED','CANCELLED','REFUNDED')),
  total INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL CHECK(qty>0), unit_price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS stock_movements(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL,
  order_id INTEGER, user_id INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_events(
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, action TEXT NOT NULL, user_id INTEGER, detail TEXT, created_at TEXT NOT NULL);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def check_pw(pw, stored):
    salt, _ = stored.split("$")
    return hmac.compare_digest(hash_pw(pw, salt), stored)


def connect():
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)  # 수동 트랜잭션
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


@contextmanager
def tx():
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")  # 쓰기 락을 먼저 잡아 동시 요청을 직렬화
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args).fetchall()]


# ---------- 시드 ----------
def seed():
    c = connect()
    c.executescript(SCHEMA)
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        c.close()
        return
    c.execute("BEGIN")
    t = now()
    c.execute("INSERT INTO users(username,name,role,pw_hash) VALUES(?,?,?,?)", ("staff", "김직원", "staff", hash_pw("staff123")))
    c.execute("INSERT INTO users(username,name,role,pw_hash) VALUES(?,?,?,?)", ("admin", "박관리", "admin", hash_pw("admin123")))
    products = [
        ("GN-001", "가나다 김치 1kg", 12000, 120, 30), ("GN-002", "가나다 총각김치 500g", 8000, 60, 20),
        ("GN-003", "국산 참기름 320ml", 15000, 45, 15), ("GN-004", "들기름 320ml", 16000, 8, 15),
        ("GN-005", "수제 떡갈비 600g", 18500, 70, 20), ("GN-006", "한우 사골곰탕 500g x 5", 24000, 35, 10),
        ("GN-007", "찰보리 쌀 10kg", 32000, 25, 10), ("GN-008", "해풍 건미역 100g", 6500, 90, 25),
        ("GN-009", "전통 고추장 1kg", 11000, 0, 15), ("GN-010", "수제 만두 1.2kg", 9800, 150, 40),
        ("GN-011", "유기농 현미 누룽지 500g", 7500, 55, 20), ("GN-012", "제주 감귤 칩 80g", 4200, 200, 50),
    ]
    for p in products:
        pid = c.execute("INSERT INTO products(sku,name,price,stock,safety_stock) VALUES(?,?,?,?,?)", p).lastrowid
        if p[3]:
            c.execute("INSERT INTO stock_movements(product_id,delta,reason,created_at) VALUES(?,?,?,?)", (pid, p[3], "초기 재고", t))
    prod = {r["id"]: r for r in c.execute("SELECT * FROM products")}
    customers = [("이서연", "010-0000-6090", "서울 강남구 테헤란로 12"), ("최민준", "010-0000-1509", "부산 해운대구 해변로 45"),
                 ("정하은", "010-0000-6807", "대전 유성구 대학로 99"), ("한도윤", "010-0000-3701", "인천 연수구 송도대로 7"),
                 ("오지우", "010-0000-4478", "광주 서구 상무중앙로 3"), ("윤서준", "010-0000-3144", "대구 수성구 달구벌대로 21")]
    # (고객idx, [(상품id,수량)], 목표상태, 며칠 전)
    plans = [(0, [(1, 2), (3, 1)], "SHIPPED", 6), (1, [(5, 1), (10, 3)], "SHIPPED", 5), (2, [(10, 2)], "REFUNDED", 5),
             (3, [(7, 1), (8, 2)], "CANCELLED", 4), (4, [(1, 1), (5, 2)], "CONFIRMED", 2), (5, [(6, 3)], "CONFIRMED", 1),
             (0, [(2, 4), (12, 5)], "PENDING", 1), (1, [(4, 2), (11, 1)], "PENDING", 0), (2, [(9, 1)], "PENDING", 0)]
    for ci, items, status, ago in plans:
        cu = customers[ci]
        ts = (datetime.now() - timedelta(days=ago)).strftime("%Y-%m-%d %H:%M:%S")
        total = sum(prod[p]["price"] * q for p, q in items)
        oid = c.execute("INSERT INTO orders(customer,phone,address,status,total,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (*cu, status, total, ts, ts)).lastrowid
        for p, q in items:
            c.execute("INSERT INTO order_items(order_id,product_id,qty,unit_price) VALUES(?,?,?,?)", (oid, p, q, prod[p]["price"]))
        deducted = status in ("CONFIRMED", "SHIPPED", "REFUNDED")
        if deducted:
            for p, q in items:
                c.execute("UPDATE products SET stock=stock-? WHERE id=?", (q, p))
                c.execute("INSERT INTO stock_movements(product_id,delta,reason,order_id,created_at) VALUES(?,?,?,?,?)", (p, -q, "주문 확정 차감", oid, ts))
        if status == "REFUNDED":
            for p, q in items:
                c.execute("UPDATE products SET stock=stock+? WHERE id=?", (q, p))
                c.execute("INSERT INTO stock_movements(product_id,delta,reason,order_id,created_at) VALUES(?,?,?,?,?)", (p, q, "환불 반품 재입고", oid, ts))
        c.execute("INSERT INTO order_events(order_id,action,detail,created_at) VALUES(?,?,?,?)", (oid, "CREATE", "주문 접수", ts))
    c.execute("COMMIT")
    c.close()


seed()


# ---------- 인증 ----------
class LoginIn(BaseModel):
    username: str
    password: str


def current_user(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    c = connect()
    try:
        r = c.execute("SELECT u.id,u.username,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,)).fetchone()
    finally:
        c.close()
    if not r:
        raise HTTPException(401, "로그인이 필요합니다.")
    return dict(r)


def admin_only(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "관리자만 수행할 수 있습니다.")
    return user


@app.post("/api/login")
def login(body: LoginIn):
    with tx() as c:
        u = c.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
        if not u or not check_pw(body.password, u["pw_hash"]):
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
        token = secrets.token_urlsafe(24)
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (token, u["id"], now()))
    return {"token": token, "user": {"username": u["username"], "name": u["name"], "role": u["role"]}}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


# ---------- 조회 ----------
@app.get("/api/products")
def products(user=Depends(current_user)):
    c = connect()
    try:
        return rows(c, "SELECT * FROM products ORDER BY sku")
    finally:
        c.close()


@app.get("/api/stock-movements")
def movements(product_id: int | None = None, user=Depends(current_user)):
    c = connect()
    try:
        sql = ("SELECT m.*,p.name product_name,u.name user_name FROM stock_movements m JOIN products p ON p.id=m.product_id "
               "LEFT JOIN users u ON u.id=m.user_id")
        args = ()
        if product_id:
            sql += " WHERE m.product_id=?"
            args = (product_id,)
        return rows(c, sql + " ORDER BY m.id DESC LIMIT 200", args)
    finally:
        c.close()


def order_detail(c, oid):
    o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    o = dict(o)
    o["items"] = rows(c, "SELECT i.*,p.name,p.sku,p.stock FROM order_items i JOIN products p ON p.id=i.product_id WHERE i.order_id=?", (oid,))
    o["events"] = rows(c, "SELECT e.*,u.name user_name FROM order_events e LEFT JOIN users u ON u.id=e.user_id WHERE e.order_id=? ORDER BY e.id", (oid,))
    return o


@app.get("/api/orders")
def orders(status: str | None = None, q: str | None = None, user=Depends(current_user)):
    c = connect()
    try:
        sql, args, w = "SELECT * FROM orders", [], []
        if status:
            w.append("status=?"); args.append(status)
        if q:
            w.append("(customer LIKE ? OR CAST(id AS TEXT)=?)"); args += [f"%{q}%", q.lstrip("#")]
        if w:
            sql += " WHERE " + " AND ".join(w)
        out = rows(c, sql + " ORDER BY id DESC LIMIT 300", args)
        for o in out:
            o["summary"] = ", ".join(f'{i["name"]} x{i["qty"]}' for i in rows(
                c, "SELECT p.name,i.qty FROM order_items i JOIN products p ON p.id=i.product_id WHERE order_id=?", (o["id"],)))
        return out
    finally:
        c.close()


@app.get("/api/orders/{oid}")
def get_order(oid: int, user=Depends(current_user)):
    c = connect()
    try:
        return order_detail(c, oid)
    finally:
        c.close()


@app.get("/api/dashboard")
def dashboard(user=Depends(current_user)):
    c = connect()
    try:
        counts = {r["status"]: r["n"] for r in rows(c, "SELECT status,COUNT(*) n FROM orders GROUP BY status")}
        low = rows(c, "SELECT * FROM products WHERE stock<=safety_stock ORDER BY stock")
        sales = c.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE status IN ('CONFIRMED','SHIPPED')").fetchone()[0]
        return {"counts": counts, "low_stock": low, "sales": sales}
    finally:
        c.close()


# ---------- 주문 생성 (쇼핑몰 주문 접수 시뮬레이션) ----------
class Item(BaseModel):
    product_id: int
    qty: int = Field(gt=0, le=10000)


class OrderIn(BaseModel):
    customer: str = Field(min_length=1, max_length=50)
    phone: str = ""
    address: str = ""
    note: str = ""
    items: list[Item] = Field(min_length=1)


def log_event(c, oid, action, user, detail=""):
    c.execute("INSERT INTO order_events(order_id,action,user_id,detail,created_at) VALUES(?,?,?,?,?)", (oid, action, user["id"], detail, now()))


@app.post("/api/orders", status_code=201)
def create_order(body: OrderIn, user=Depends(current_user)):
    with tx() as c:
        merged: dict[int, int] = {}
        for i in body.items:  # 같은 상품 중복 행 합산
            merged[i.product_id] = merged.get(i.product_id, 0) + i.qty
        total, lines = 0, []
        for pid, qty in merged.items():
            p = c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not p:
                raise HTTPException(404, f"상품 #{pid} 이(가) 없습니다.")
            total += p["price"] * qty
            lines.append((pid, qty, p["price"]))
        t = now()
        oid = c.execute("INSERT INTO orders(customer,phone,address,status,total,created_at,updated_at,note) VALUES(?,?,?,?,?,?,?,?)",
                        (body.customer, body.phone, body.address, "PENDING", total, t, t, body.note)).lastrowid
        for pid, qty, price in lines:
            c.execute("INSERT INTO order_items(order_id,product_id,qty,unit_price) VALUES(?,?,?,?)", (oid, pid, qty, price))
        log_event(c, oid, "CREATE", user, "주문 접수")
        return order_detail(c, oid)


# ---------- 상태 전이 ----------
def transition(c, oid, allowed, new_status):
    """현재 상태가 allowed 일 때만 원자적으로 전이. 이전 상태를 반환."""
    o = c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    cur = o["status"]
    if cur not in allowed:
        raise HTTPException(409, f"현재 상태({cur})에서는 처리할 수 없습니다.")
    n = c.execute("UPDATE orders SET status=?,updated_at=? WHERE id=? AND status=?", (new_status, now(), oid, cur)).rowcount
    if n != 1:
        raise HTTPException(409, "다른 처리와 충돌했습니다. 새로고침 후 다시 시도하세요.")
    return cur


def deduct(c, oid, user):
    short = []
    for it in rows(c, "SELECT i.product_id,i.qty,p.name FROM order_items i JOIN products p ON p.id=i.product_id WHERE order_id=?", (oid,)):
        n = c.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=?", (it["qty"], it["product_id"], it["qty"])).rowcount
        if n != 1:
            have = c.execute("SELECT stock FROM products WHERE id=?", (it["product_id"],)).fetchone()[0]
            short.append(f'{it["name"]} (필요 {it["qty"]}, 재고 {have})')
            continue
        c.execute("INSERT INTO stock_movements(product_id,delta,reason,order_id,user_id,created_at) VALUES(?,?,?,?,?,?)",
                  (it["product_id"], -it["qty"], "주문 확정 차감", oid, user["id"], now()))
    if short:  # tx() 가 롤백하므로 일부 차감도 모두 되돌아간다
        raise HTTPException(409, "재고 부족으로 확정할 수 없습니다: " + "; ".join(short))


def restock(c, oid, user, reason):
    for it in rows(c, "SELECT product_id,qty FROM order_items WHERE order_id=?", (oid,)):
        c.execute("UPDATE products SET stock=stock+? WHERE id=?", (it["qty"], it["product_id"]))
        c.execute("INSERT INTO stock_movements(product_id,delta,reason,order_id,user_id,created_at) VALUES(?,?,?,?,?,?)",
                  (it["product_id"], it["qty"], reason, oid, user["id"], now()))


@app.post("/api/orders/{oid}/confirm")
def confirm(oid: int, user=Depends(current_user)):
    with tx() as c:
        transition(c, oid, {"PENDING"}, "CONFIRMED")
        deduct(c, oid, user)
        log_event(c, oid, "CONFIRM", user, "주문 확정 · 재고 차감")
        return order_detail(c, oid)


@app.post("/api/orders/{oid}/ship")
def ship(oid: int, user=Depends(current_user)):
    with tx() as c:
        transition(c, oid, {"CONFIRMED"}, "SHIPPED")
        log_event(c, oid, "SHIP", user, "출고 처리")
        return order_detail(c, oid)


@app.post("/api/orders/{oid}/cancel")
def cancel(oid: int, user=Depends(current_user)):
    with tx() as c:
        prev = transition(c, oid, {"PENDING", "CONFIRMED"}, "CANCELLED")
        if prev == "CONFIRMED":
            restock(c, oid, user, "주문 취소 재고 복원")
        log_event(c, oid, "CANCEL", user, "주문 취소" + (" · 재고 복원" if prev == "CONFIRMED" else ""))
        return order_detail(c, oid)


class RefundIn(BaseModel):
    restock: bool = True
    reason: str = ""


@app.post("/api/orders/{oid}/refund")
def refund(oid: int, body: RefundIn, user=Depends(admin_only)):
    with tx() as c:
        transition(c, oid, {"SHIPPED"}, "REFUNDED")
        if body.restock:
            restock(c, oid, user, "환불 반품 재입고")
        log_event(c, oid, "REFUND", user, f'환불 ({"재입고" if body.restock else "재고 미반영/폐기"}) {body.reason}'.strip())
        return order_detail(c, oid)


# ---------- 입고 ----------
class ReceiveIn(BaseModel):
    qty: int = Field(gt=0, le=100000)
    reason: str = "입고"


@app.post("/api/products/{pid}/receive")
def receive(pid: int, body: ReceiveIn, user=Depends(current_user)):
    with tx() as c:
        if c.execute("UPDATE products SET stock=stock+? WHERE id=?", (body.qty, pid)).rowcount != 1:
            raise HTTPException(404, "상품을 찾을 수 없습니다.")
        c.execute("INSERT INTO stock_movements(product_id,delta,reason,user_id,created_at) VALUES(?,?,?,?,?)",
                  (pid, body.qty, body.reason or "입고", user["id"], now()))
        return dict(c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
