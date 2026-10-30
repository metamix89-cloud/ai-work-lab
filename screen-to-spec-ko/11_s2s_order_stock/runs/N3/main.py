import csv
import os
import sqlite3
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB_PATH = os.path.join(BASE, "backoffice.db")

# action -> (허용되는 현재 상태, 다음 상태)
ACTIONS = {
    "confirm": ({"placed"}, "confirmed"),
    "ship": ({"confirmed"}, "shipped"),
    "cancel": ({"placed", "confirmed"}, "cancelled"),
    "refund": ({"shipped"}, "refunded"),
}

lock = threading.Lock()


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
        CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                                  stock INTEGER NOT NULL CHECK (stock >= 0));
        CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT NOT NULL,
                                status TEXT NOT NULL, ordered_at TEXT NOT NULL);
        CREATE TABLE bo_order_lines (order_id TEXT NOT NULL, product_id TEXT NOT NULL, qty INTEGER NOT NULL,
                                     seq INTEGER NOT NULL);
    """)
    conn.executemany("INSERT INTO bo_users VALUES (?,?,?)",
                     [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    conn.executemany("INSERT INTO bo_products VALUES (?,?,?)",
                     [(r["product_id"], r["name"], int(r["stock"])) for r in read_csv("products.csv")])
    conn.executemany("INSERT INTO bo_orders VALUES (?,?,?,?)",
                     [(r["order_id"], r["customer"], r["status"], r["ordered_at"]) for r in read_csv("orders.csv")])
    conn.executemany("INSERT INTO bo_order_lines VALUES (?,?,?,?)",
                     [(r["order_id"], r["product_id"], int(r["qty"]), i)
                      for i, r in enumerate(read_csv("order_lines.csv"))])
    return conn


db = init_db()
app = FastAPI()


def products():
    return [dict(r) for r in db.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")]


def order_dict(row):
    lines = db.execute(
        "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l "
        "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ? ORDER BY l.seq",
        (row["order_id"],)).fetchall()
    return {"order_id": row["order_id"], "customer": row["customer"], "status": row["status"],
            "ordered_at": row["ordered_at"], "lines": [dict(l) for l in lines]}


def reject(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def get_users():
    with lock:
        return [dict(r) for r in db.execute("SELECT user_id, name, role FROM bo_users ORDER BY rowid")]


@app.get("/api/products")
def get_products():
    with lock:
        return products()


@app.get("/api/orders")
def get_orders():
    with lock:
        rows = db.execute("SELECT * FROM bo_orders ORDER BY ordered_at, rowid").fetchall()
        return [order_dict(r) for r in rows]


@app.post("/api/orders/{order_id}/{action}")
async def do_action(order_id: str, action: str, request: Request):
    # R8: 400(본문) -> 404(주문 · 사용자 · 동작) -> 403(권한) -> 409(상태 · 재고)
    try:
        body = await request.json()
    except Exception:
        body = None
    user_id = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user_id, str):
        return reject(400, "사용자를 확인하세요")
    with lock:
        order = db.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        if order is None:
            return reject(404, "주문을 찾을 수 없습니다")
        user = db.execute("SELECT * FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
        if user is None:
            return reject(404, "사용자를 찾을 수 없습니다")
        if action not in ACTIONS:
            return reject(404, "없는 동작입니다")
        if action == "refund" and user["role"] != "manager":
            return reject(403, "관리자만 할 수 있습니다")
        allowed, new_status = ACTIONS[action]
        if order["status"] not in allowed:
            return reject(409, "지금 상태에서는 할 수 없습니다")
        lines = db.execute("SELECT product_id, qty FROM bo_order_lines WHERE order_id = ?", (order_id,)).fetchall()
        db.execute("BEGIN IMMEDIATE")
        try:
            if action == "confirm":
                for l in lines:
                    cur = db.execute("UPDATE bo_products SET stock = stock - ? WHERE product_id = ? AND stock >= ?",
                                     (l["qty"], l["product_id"], l["qty"]))
                    if cur.rowcount != 1:
                        name = db.execute("SELECT name FROM bo_products WHERE product_id = ?",
                                          (l["product_id"],)).fetchone()
                        db.execute("ROLLBACK")
                        return reject(409, "재고가 부족합니다: %s" % (name["name"] if name else l["product_id"]))
            elif action == "cancel" and order["status"] == "confirmed":
                for l in lines:
                    db.execute("UPDATE bo_products SET stock = stock + ? WHERE product_id = ?",
                               (l["qty"], l["product_id"]))
            db.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (new_status, order_id))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        row = db.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        return {"order": order_dict(row), "products": products()}
