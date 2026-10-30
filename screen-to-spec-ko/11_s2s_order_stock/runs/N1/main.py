import csv
import os
import sqlite3
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "backoffice.db")
LOCK = threading.Lock()
DB = None

SCHEMA = """
CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    stock INTEGER NOT NULL CHECK (stock >= 0));
CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT NOT NULL, status TEXT NOT NULL,
    ordered_at TEXT NOT NULL);
CREATE TABLE bo_order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL,
    product_id TEXT NOT NULL, qty INTEGER NOT NULL CHECK (qty >= 1));
"""


def read_csv(name):
    with open(os.path.join(ROOT, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    global DB
    if DB is not None:
        DB.close()
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    DB = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    DB.row_factory = sqlite3.Row
    DB.executescript(SCHEMA)
    DB.execute("BEGIN")
    DB.executemany("INSERT INTO bo_users VALUES (?,?,?)",
                   [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    DB.executemany("INSERT INTO bo_products VALUES (?,?,?)",
                   [(r["product_id"], r["name"], int(r["stock"])) for r in read_csv("products.csv")])
    DB.executemany("INSERT INTO bo_orders VALUES (?,?,?,?)",
                   [(r["order_id"], r["customer"], r["status"], r["ordered_at"]) for r in read_csv("orders.csv")])
    DB.executemany("INSERT INTO bo_order_lines (order_id, product_id, qty) VALUES (?,?,?)",
                   [(r["order_id"], r["product_id"], int(r["qty"])) for r in read_csv("order_lines.csv")])
    DB.execute("COMMIT")


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)

# action -> (허용되는 현재 상태, 다음 상태)
ACTIONS = {
    "confirm": (("placed",), "confirmed"),
    "ship": (("confirmed",), "shipped"),
    "cancel": (("placed", "confirmed"), "cancelled"),
    "refund": (("shipped",), "refunded"),
}


def fail(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def order_json(oid):
    o = DB.execute("SELECT * FROM bo_orders WHERE order_id=?", (oid,)).fetchone()
    lines = DB.execute(
        "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l JOIN bo_products p USING(product_id) "
        "WHERE l.order_id=? ORDER BY l.id", (oid,)).fetchall()
    return {"order_id": o["order_id"], "customer": o["customer"], "status": o["status"],
            "ordered_at": o["ordered_at"], "lines": [dict(l) for l in lines]}


def products_json():
    return [dict(r) for r in DB.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")]


@app.get("/api/users")
def users():
    with LOCK:
        return [dict(r) for r in DB.execute("SELECT user_id, name, role FROM bo_users ORDER BY rowid")]


@app.get("/api/products")
def products():
    with LOCK:
        return products_json()


@app.get("/api/orders")
def orders():
    with LOCK:
        ids = [r[0] for r in DB.execute("SELECT order_id FROM bo_orders ORDER BY ordered_at, order_id")]
        return [order_json(i) for i in ids]


@app.post("/api/orders/{order_id}/{action}")
async def do_action(order_id: str, action: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    user = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user, str) or not user:
        return fail(400, "사용자를 확인하세요")
    return run_action(order_id, action, user)


def run_action(order_id, action, user_id):
    with LOCK:
        order = DB.execute("SELECT status FROM bo_orders WHERE order_id=?", (order_id,)).fetchone()
        if order is None:
            return fail(404, "없는 주문입니다")
        u = DB.execute("SELECT role FROM bo_users WHERE user_id=?", (user_id,)).fetchone()
        if u is None:
            return fail(404, "없는 사용자입니다")
        if action not in ACTIONS:
            return fail(404, "없는 동작입니다")
        if action == "refund" and u["role"] != "manager":
            return fail(403, "관리자만 할 수 있습니다")
        allowed, nxt = ACTIONS[action]
        status = order["status"]
        if status not in allowed:
            return fail(409, "지금 상태에서는 할 수 없습니다")
        lines = DB.execute(
            "SELECT l.product_id, p.name, p.stock, l.qty FROM bo_order_lines l "
            "JOIN bo_products p USING(product_id) WHERE l.order_id=?", (order_id,)).fetchall()
        need = {}
        for l in lines:
            need.setdefault(l["product_id"], [l["name"], l["stock"], 0])[2] += l["qty"]
        if action == "confirm":
            for name, stock, qty in need.values():
                if stock < qty:
                    return fail(409, "재고가 부족합니다: " + name)
        DB.execute("BEGIN IMMEDIATE")
        try:
            if action == "confirm":
                for pid, (_n, _s, qty) in need.items():
                    DB.execute("UPDATE bo_products SET stock=stock-? WHERE product_id=?", (qty, pid))
            elif action == "cancel" and status == "confirmed":
                for pid, (_n, _s, qty) in need.items():
                    DB.execute("UPDATE bo_products SET stock=stock+? WHERE product_id=?", (qty, pid))
            DB.execute("UPDATE bo_orders SET status=? WHERE order_id=?", (nxt, order_id))
            DB.execute("COMMIT")
        except Exception:
            DB.execute("ROLLBACK")
            raise
        return {"order": order_json(order_id), "products": products_json()}


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"), media_type="text/html; charset=utf-8")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
