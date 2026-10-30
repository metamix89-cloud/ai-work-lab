import csv
import os
import sqlite3
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "backoffice.db")
LOCK = threading.Lock()
ACTIONS = {
    # action: (허용 상태, 다음 상태)
    "confirm": (("placed",), "confirmed"),
    "ship": (("confirmed",), "shipped"),
    "cancel": (("placed", "confirmed"), "cancelled"),
    "refund": (("shipped",), "refunded"),
}


def connect():
    con = sqlite3.connect(DB, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    con = connect()
    con.executescript("""
        CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT, stock INTEGER NOT NULL CHECK (stock >= 0));
        CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT, status TEXT, ordered_at TEXT);
        CREATE TABLE bo_order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, product_id TEXT, qty INTEGER);
    """)
    con.execute("BEGIN")
    con.executemany("INSERT INTO bo_users VALUES (?,?,?)",
                    [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    con.executemany("INSERT INTO bo_products VALUES (?,?,?)",
                    [(r["product_id"], r["name"], int(r["stock"])) for r in read_csv("products.csv")])
    con.executemany("INSERT INTO bo_orders VALUES (?,?,?,?)",
                    [(r["order_id"], r["customer"], r["status"], r["ordered_at"]) for r in read_csv("orders.csv")])
    con.executemany("INSERT INTO bo_order_lines (order_id, product_id, qty) VALUES (?,?,?)",
                    [(r["order_id"], r["product_id"], int(r["qty"])) for r in read_csv("order_lines.csv")])
    con.execute("COMMIT")
    con.close()


def products(con):
    return [dict(r) for r in con.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")]


def order_dict(con, row):
    lines = con.execute(
        "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l "
        "LEFT JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ? ORDER BY l.id",
        (row["order_id"],)).fetchall()
    return {"order_id": row["order_id"], "customer": row["customer"], "status": row["status"],
            "ordered_at": row["ordered_at"], "lines": [dict(l) for l in lines]}


def reject(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


init_db()
app = FastAPI()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    with LOCK:
        con = connect()
        try:
            return [dict(r) for r in con.execute("SELECT user_id, name, role FROM bo_users ORDER BY rowid")]
        finally:
            con.close()


@app.get("/api/products")
def list_products():
    with LOCK:
        con = connect()
        try:
            return products(con)
        finally:
            con.close()


@app.get("/api/orders")
def orders():
    with LOCK:
        con = connect()
        try:
            rows = con.execute("SELECT * FROM bo_orders ORDER BY ordered_at, rowid").fetchall()
            return [order_dict(con, r) for r in rows]
        finally:
            con.close()


@app.post("/api/orders/{order_id}/{action}")
async def do_action(order_id: str, action: str, request: Request):
    # 1) 본문만 보면 아는 것 -> 400
    try:
        body = await request.json()
    except Exception:
        body = None
    user_id = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user_id, str) or not user_id:
        return reject(400, "사용자를 확인하세요")

    # 락 하나로 확인 · 차감 · 상태 변경을 한 덩어리로 처리 (동시 확정 방지)
    with LOCK:
        con = connect()
        try:
            # 2) 없는 주문 · 사용자 · 동작 -> 404
            order = con.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
            if order is None:
                return reject(404, "주문을 찾을 수 없습니다")
            user = con.execute("SELECT * FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
            if user is None:
                return reject(404, "사용자를 찾을 수 없습니다")
            if action not in ACTIONS:
                return reject(404, "알 수 없는 동작입니다")
            # 3) 권한 -> 403
            if action == "refund" and user["role"] != "manager":
                return reject(403, "관리자만 할 수 있습니다")
            # 4) 상태 · 재고 -> 409
            allowed, nxt = ACTIONS[action]
            if order["status"] not in allowed:
                return reject(409, "지금 상태에서는 할 수 없습니다")
            con.execute("BEGIN IMMEDIATE")
            try:
                lines = con.execute("SELECT product_id, qty FROM bo_order_lines WHERE order_id = ?",
                                    (order_id,)).fetchall()
                if action == "confirm":
                    need = {}
                    for l in lines:
                        need[l["product_id"]] = need.get(l["product_id"], 0) + l["qty"]
                    for pid, qty in need.items():
                        p = con.execute("SELECT name, stock FROM bo_products WHERE product_id = ?", (pid,)).fetchone()
                        if p is None or p["stock"] < qty:
                            con.execute("ROLLBACK")
                            return reject(409, "재고가 부족합니다: %s" % (p["name"] if p else pid))
                    for pid, qty in need.items():
                        con.execute("UPDATE bo_products SET stock = stock - ? WHERE product_id = ?", (qty, pid))
                elif action == "cancel" and order["status"] == "confirmed":
                    for l in lines:
                        con.execute("UPDATE bo_products SET stock = stock + ? WHERE product_id = ?",
                                    (l["qty"], l["product_id"]))
                con.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (nxt, order_id))
                con.execute("COMMIT")
            except Exception:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise
            row = con.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
            return {"order": order_dict(con, row), "products": products(con)}
        finally:
            con.close()
