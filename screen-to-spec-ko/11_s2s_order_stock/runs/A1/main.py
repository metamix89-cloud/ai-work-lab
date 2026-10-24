"""가나다식품 주문 · 재고 백오피스 (FastAPI + SQLite)

재고 규칙
- 주문 확정(PENDING -> CONFIRMED) 시 재고를 차감한다. 한 상품이라도 부족하면 전체 롤백.
- 확정 주문을 취소(CONFIRMED -> CANCELLED)하면 재고를 되돌린다. 접수 상태 취소는 재고 변동 없음.
- 출고(CONFIRMED -> SHIPPED)는 재고 변동 없음(확정 시 이미 차감).
- 환불(SHIPPED -> REFUNDED, 관리자 전용)은 상품이 반품 입고된 경우(restock=true)에만 재고를 되돌린다.
- 재고 차감은 `UPDATE ... WHERE stock >= qty` 조건부 갱신 + DB CHECK(stock >= 0)로 이중 방어하고,
  상태 전이도 `WHERE status = 이전상태` 조건부 갱신이라 동시 요청에도 이중 처리되지 않는다.
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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.environ.get("GANADA_DB", str(BASE / "ganada.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('staff','admin')), salt TEXT NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
  price INTEGER NOT NULL CHECK(price >= 0),
  stock INTEGER NOT NULL CHECK(stock >= 0),
  safety_stock INTEGER NOT NULL DEFAULT 20);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, order_no TEXT UNIQUE NOT NULL, customer TEXT NOT NULL, phone TEXT NOT NULL,
  address TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PENDING','CONFIRMED','SHIPPED','CANCELLED','REFUNDED')),
  total INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER NOT NULL REFERENCES products(id),
  qty INTEGER NOT NULL CHECK(qty > 0), unit_price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS order_events(
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  from_status TEXT, to_status TEXT NOT NULL, actor TEXT NOT NULL, note TEXT, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stock_log(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  order_id INTEGER REFERENCES orders(id), delta INTEGER NOT NULL, reason TEXT NOT NULL,
  actor TEXT NOT NULL, at TEXT NOT NULL);
"""

STATUS_KO = {"PENDING": "접수", "CONFIRMED": "확정", "SHIPPED": "출고", "CANCELLED": "취소", "REFUNDED": "환불"}


def now(delta_hours: float = 0) -> str:
    return (datetime.now() + timedelta(hours=delta_hours)).strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    # isolation_level=None: 트랜잭션은 직접 BEGIN IMMEDIATE / COMMIT 으로 제어
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


@contextmanager
def tx(con: sqlite3.Connection):
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def get_db():
    con = connect()
    try:
        yield con
    finally:
        con.close()


# ---------------------------------------------------------------- 인증
def hash_pw(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()


SESSIONS: dict[str, dict] = {}


def current_user(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    user = SESSIONS.get(token)
    if not user:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


def admin_only(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "관리자만 수행할 수 있습니다.")
    return user


# ---------------------------------------------------------------- 도메인 로직
def _items(con, order_id):
    return con.execute(
        "SELECT oi.product_id, oi.qty, p.name FROM order_items oi JOIN products p ON p.id=oi.product_id "
        "WHERE oi.order_id=? ORDER BY oi.id", (order_id,)).fetchall()


def _move_stock(con, product_id, delta, order_id, reason, actor):
    """재고 증감. 마이너스가 되면 False. (호출자가 트랜잭션 안에서 사용)"""
    cur = con.execute("UPDATE products SET stock = stock + ? WHERE id=? AND stock + ? >= 0",
                      (delta, product_id, delta))
    if cur.rowcount != 1:
        return False
    con.execute("INSERT INTO stock_log(product_id,order_id,delta,reason,actor,at) VALUES(?,?,?,?,?,?)",
                (product_id, order_id, delta, reason, actor, now()))
    return True


def _set_status(con, order_id, frm, to, actor, note=None):
    """상태 전이는 현재 상태가 frm 일 때만 성공 (중복 처리 방지)."""
    cur = con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=? AND status=?",
                      (to, now(), order_id, frm))
    if cur.rowcount != 1:
        row = con.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(404, "주문을 찾을 수 없습니다.")
        raise HTTPException(409, f"현재 상태가 '{STATUS_KO[row['status']]}'이라 처리할 수 없습니다.")
    con.execute("INSERT INTO order_events(order_id,from_status,to_status,actor,note,at) VALUES(?,?,?,?,?,?)",
                (order_id, frm, to, actor, note, now()))


def create_order(con, customer, phone, address, lines, actor, created_at=None):
    if not lines:
        raise HTTPException(422, "주문 상품이 없습니다.")
    merged: dict[int, int] = {}
    for pid, qty in lines:
        merged[pid] = merged.get(pid, 0) + qty
    with tx(con):
        total, rows = 0, []
        for pid, qty in merged.items():
            p = con.execute("SELECT id, price FROM products WHERE id=?", (pid,)).fetchone()
            if not p:
                raise HTTPException(404, f"상품(id={pid})을 찾을 수 없습니다.")
            rows.append((pid, qty, p["price"]))
            total += qty * p["price"]
        ts = created_at or now()
        oid = con.execute(
            "INSERT INTO orders(order_no,customer,phone,address,status,total,created_at,updated_at) "
            "VALUES('TMP',?,?,?,'PENDING',?,?,?)", (customer, phone, address, total, ts, ts)).lastrowid
        con.execute("UPDATE orders SET order_no=? WHERE id=?", (f"GN{datetime.now():%y%m%d}-{oid:04d}", oid))
        con.executemany("INSERT INTO order_items(order_id,product_id,qty,unit_price) VALUES(?,?,?,?)",
                        [(oid, *r) for r in rows])
        con.execute("INSERT INTO order_events(order_id,from_status,to_status,actor,note,at) VALUES(?,?,?,?,?,?)",
                    (oid, None, "PENDING", actor, "쇼핑몰 주문 접수", ts))
    return oid


def confirm_order(con, oid, actor):
    with tx(con):
        _set_status(con, oid, "PENDING", "CONFIRMED", actor)
        short = []
        for it in _items(con, oid):
            if not _move_stock(con, it["product_id"], -it["qty"], oid, "주문 확정 차감", actor):
                have = con.execute("SELECT stock FROM products WHERE id=?", (it["product_id"],)).fetchone()["stock"]
                short.append(f"{it['name']} (재고 {have}, 필요 {it['qty']})")
        if short:  # 예외 -> tx()가 ROLLBACK: 상태 전이와 이미 차감한 재고 모두 원복
            raise HTTPException(409, "재고 부족으로 확정할 수 없습니다: " + ", ".join(short))


def ship_order(con, oid, actor):
    with tx(con):
        _set_status(con, oid, "CONFIRMED", "SHIPPED", actor)


def cancel_order(con, oid, actor, note=None):
    with tx(con):
        row = con.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
        if not row:
            raise HTTPException(404, "주문을 찾을 수 없습니다.")
        if row["status"] not in ("PENDING", "CONFIRMED"):
            raise HTTPException(409, f"'{STATUS_KO[row['status']]}' 상태의 주문은 취소할 수 없습니다. "
                                     "출고된 주문은 관리자 환불을 이용하세요.")
        frm = row["status"]
        _set_status(con, oid, frm, "CANCELLED", actor, note)
        if frm == "CONFIRMED":
            for it in _items(con, oid):
                _move_stock(con, it["product_id"], it["qty"], oid, "주문 취소 복원", actor)


def refund_order(con, oid, actor, restock, note=None):
    with tx(con):
        _set_status(con, oid, "SHIPPED", "REFUNDED", actor, note)
        if restock:
            for it in _items(con, oid):
                _move_stock(con, it["product_id"], it["qty"], oid, "환불 반품 입고", actor)


# ---------------------------------------------------------------- API
app = FastAPI(title="가나다식품 주문·재고 백오피스")


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, con=Depends(get_db)):
    u = con.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
    if not u or not hmac.compare_digest(u["pw_hash"], hash_pw(body.password, u["salt"])):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
    token = secrets.token_hex(24)
    SESSIONS[token] = {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"]}
    return {"token": token, "user": SESSIONS[token]}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


@app.get("/api/dashboard")
def dashboard(con=Depends(get_db), user=Depends(current_user)):
    counts = {s: 0 for s in STATUS_KO}
    for r in con.execute("SELECT status, COUNT(*) c FROM orders GROUP BY status"):
        counts[r["status"]] = r["c"]
    low = con.execute("SELECT COUNT(*) c FROM products WHERE stock <= safety_stock").fetchone()["c"]
    sales = con.execute("SELECT COALESCE(SUM(total),0) s FROM orders WHERE status IN ('CONFIRMED','SHIPPED')"
                        ).fetchone()["s"]
    return {"counts": counts, "low_stock": low, "sales": sales}


@app.get("/api/products")
def products(con=Depends(get_db), user=Depends(current_user)):
    return [dict(r) for r in con.execute("SELECT * FROM products ORDER BY category, name")]


class AdjustIn(BaseModel):
    delta: int
    reason: str = Field(min_length=1, max_length=100)


@app.post("/api/products/{pid}/adjust")
def adjust_stock(pid: int, body: AdjustIn, con=Depends(get_db), user=Depends(admin_only)):
    if body.delta == 0:
        raise HTTPException(422, "변동 수량이 0입니다.")
    with tx(con):
        if not con.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
            raise HTTPException(404, "상품을 찾을 수 없습니다.")
        if not _move_stock(con, pid, body.delta, None, body.reason, user["username"]):
            raise HTTPException(409, "재고가 마이너스가 될 수 없습니다.")
    return dict(con.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())


@app.get("/api/stock-log")
def stock_log(con=Depends(get_db), user=Depends(current_user)):
    rows = con.execute(
        "SELECT l.*, p.name product, o.order_no FROM stock_log l JOIN products p ON p.id=l.product_id "
        "LEFT JOIN orders o ON o.id=l.order_id ORDER BY l.id DESC LIMIT 100")
    return [dict(r) for r in rows]


def _order_detail(con, oid):
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    d = dict(o)
    d["items"] = [dict(r) for r in con.execute(
        "SELECT oi.product_id, p.name, p.stock, oi.qty, oi.unit_price FROM order_items oi "
        "JOIN products p ON p.id=oi.product_id WHERE oi.order_id=? ORDER BY oi.id", (oid,))]
    d["events"] = [dict(r) for r in con.execute(
        "SELECT * FROM order_events WHERE order_id=? ORDER BY id", (oid,))]
    return d


@app.get("/api/orders")
def list_orders(status: str = "", q: str = "", con=Depends(get_db), user=Depends(current_user)):
    sql, args = "SELECT * FROM orders WHERE 1=1", []
    if status:
        sql += " AND status=?"
        args.append(status)
    if q:
        sql += " AND (order_no LIKE ? OR customer LIKE ? OR phone LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY id DESC"
    return [dict(r) for r in con.execute(sql, args)]


@app.get("/api/orders/{oid}")
def get_order(oid: int, con=Depends(get_db), user=Depends(current_user)):
    return _order_detail(con, oid)


class LineIn(BaseModel):
    product_id: int
    qty: int = Field(gt=0, le=10000)


class OrderIn(BaseModel):
    customer: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=1, max_length=30)
    address: str = Field(min_length=1, max_length=200)
    items: list[LineIn] = Field(min_length=1)


@app.post("/api/orders")
def new_order(body: OrderIn, con=Depends(get_db), user=Depends(current_user)):
    oid = create_order(con, body.customer, body.phone, body.address,
                       [(i.product_id, i.qty) for i in body.items], user["username"])
    return _order_detail(con, oid)


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=200)


@app.post("/api/orders/{oid}/confirm")
def api_confirm(oid: int, con=Depends(get_db), user=Depends(current_user)):
    confirm_order(con, oid, user["username"])
    return _order_detail(con, oid)


@app.post("/api/orders/{oid}/ship")
def api_ship(oid: int, con=Depends(get_db), user=Depends(current_user)):
    ship_order(con, oid, user["username"])
    return _order_detail(con, oid)


@app.post("/api/orders/{oid}/cancel")
def api_cancel(oid: int, body: NoteIn | None = None, con=Depends(get_db), user=Depends(current_user)):
    cancel_order(con, oid, user["username"], body.note if body else None)
    return _order_detail(con, oid)


class RefundIn(BaseModel):
    restock: bool = True
    note: str | None = Field(default=None, max_length=200)


@app.post("/api/orders/{oid}/refund")
def api_refund(oid: int, body: RefundIn, con=Depends(get_db), user=Depends(admin_only)):
    refund_order(con, oid, user["username"], body.restock, body.note)
    return _order_detail(con, oid)


# ---------------------------------------------------------------- 가상 데이터
def seed(con):
    users = [("staff", "김직원", "staff", "staff123"), ("admin", "박관리", "admin", "admin123")]
    for un, name, role, pw in users:
        salt = secrets.token_hex(8)
        con.execute("INSERT INTO users(username,name,role,salt,pw_hash) VALUES(?,?,?,?,?)",
                    (un, name, role, salt, hash_pw(pw, salt)))
    prods = [  # sku, 이름, 분류, 가격, 초기재고, 안전재고
        ("GN-RC-001", "가나다 햇쌀밥 210g x 12", "즉석밥", 14900, 120, 30),
        ("GN-RC-002", "가나다 현미밥 210g x 12", "즉석밥", 16900, 60, 30),
        ("GN-NO-001", "가나다 매콤라면 5입", "면류", 4500, 300, 50),
        ("GN-NO-002", "가나다 잔치국수 3인", "면류", 3800, 15, 20),
        ("GN-SA-001", "가나다 쌈장 500g", "소스", 4200, 80, 20),
        ("GN-SA-002", "가나다 고추장 1kg", "소스", 9800, 45, 20),
        ("GN-KM-001", "가나다 포기김치 1kg", "김치", 12900, 40, 25),
        ("GN-KM-002", "가나다 총각김치 500g", "김치", 7900, 8, 15),
        ("GN-FZ-001", "가나다 왕만두 1kg", "냉동", 8900, 70, 30),
        ("GN-FZ-002", "가나다 돈까스 4입", "냉동", 7500, 55, 30),
        ("GN-SN-001", "가나다 꿀약과 10개입", "간식", 6900, 90, 20),
        ("GN-SN-002", "가나다 쌀과자 선물세트", "간식", 12000, 25, 10),
        ("GN-DR-001", "가나다 보리차 1.5L x 6", "음료", 7800, 150, 40),
        ("GN-DR-002", "가나다 식혜 238ml x 12", "음료", 9900, 0, 20),
        ("GN-OI-001", "가나다 참기름 320ml", "양념", 11900, 35, 15),
    ]
    con.executemany("INSERT INTO products(sku,name,category,price,stock,safety_stock) VALUES(?,?,?,?,?,?)", prods)
    pid = {r["sku"]: r["id"] for r in con.execute("SELECT id, sku FROM products")}
    P = lambda sku: pid[sku]  # noqa: E731
    # (고객, 전화, 주소, [(sku, 수량)], 목표상태, 몇 시간 전)
    orders = [
        ("이서연", "010-0000-2831", "서울 마포구 월드컵북로 21", [("GN-RC-001", 2), ("GN-SA-001", 1)], "SHIPPED", 90),
        ("최민준", "010-0000-2643", "경기 성남시 분당구 판교로 10", [("GN-NO-001", 4), ("GN-FZ-001", 2)], "SHIPPED", 80),
        ("정하윤", "010-0000-4839", "부산 해운대구 센텀로 55", [("GN-KM-001", 3)], "SHIPPED", 70),
        ("한지우", "010-0000-2640", "대전 서구 둔산로 100", [("GN-SN-002", 2), ("GN-OI-001", 1)], "REFUNDED", 66),
        ("오도윤", "010-0000-5334", "인천 연수구 송도동 12", [("GN-DR-001", 3)], "CANCELLED", 60),
        ("윤서아", "010-0000-9540", "광주 북구 첨단로 7", [("GN-FZ-002", 3), ("GN-RC-002", 1)], "CANCELLED", 50),
        ("강예준", "010-0000-5467", "대구 수성구 달구벌대로 300", [("GN-NO-001", 6), ("GN-SA-002", 2)], "CONFIRMED", 30),
        ("조은서", "010-0000-1100", "서울 송파구 올림픽로 240", [("GN-RC-001", 3), ("GN-KM-002", 2)], "CONFIRMED", 26),
        ("신우진", "010-0000-2478", "경기 수원시 영통구 광교로 5", [("GN-SN-001", 4)], "CONFIRMED", 20),
        ("임채원", "010-0000-4256", "울산 남구 삼산로 80", [("GN-RC-002", 2), ("GN-FZ-001", 1)], "PENDING", 10),
        ("송지호", "010-0000-4226", "서울 강남구 테헤란로 152", [("GN-NO-002", 20)], "PENDING", 6),  # 재고 부족 시연
        ("배수아", "010-0000-7300", "제주 제주시 연동 33", [("GN-DR-002", 1), ("GN-OI-001", 2)], "PENDING", 3),  # 재고 0 시연
        ("문태양", "010-0000-7534", "경기 고양시 일산동구 중앙로 9", [("GN-KM-001", 2), ("GN-SA-001", 3)], "PENDING", 1),
    ]
    actor = "seed"
    for cust, phone, addr, lines, target, hrs_ago in orders:
        oid = create_order(con, cust, phone, addr, [(P(s), q) for s, q in lines], actor, now(-hrs_ago))
        if target in ("CONFIRMED", "SHIPPED", "REFUNDED"):
            confirm_order(con, oid, "staff")
        if target in ("SHIPPED", "REFUNDED"):
            ship_order(con, oid, "staff")
        if target == "REFUNDED":
            refund_order(con, oid, "admin", True, "고객 변심 반품")
        if target == "CANCELLED":
            confirm_order(con, oid, "staff")
            cancel_order(con, oid, "staff", "고객 요청 취소")


def init_db():
    con = connect()
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        seed(con)
    con.close()


init_db()
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
