import csv
import os
import sqlite3
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "backoffice.db")
LOCK = threading.Lock()

STATUS_AFTER = {"confirm": "confirmed", "ship": "shipped", "cancel": "cancelled", "refund": "refunded"}
ALLOWED_FROM = {"confirm": ("placed",), "ship": ("confirmed",),
                "cancel": ("placed", "confirmed"), "refund": ("shipped",)}


def read_csv(name):
    with open(os.path.join(ROOT, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    db = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT,
                                  stock INTEGER CHECK (stock >= 0));
        CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT, status TEXT, ordered_at TEXT);
        CREATE TABLE bo_order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT,
                                     product_id TEXT, qty INTEGER);
    """)
    db.executemany("INSERT INTO bo_users VALUES (?,?,?)",
                   [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    db.executemany("INSERT INTO bo_products VALUES (?,?,?)",
                   [(r["product_id"], r["name"], int(r["stock"])) for r in read_csv("products.csv")])
    db.executemany("INSERT INTO bo_orders VALUES (?,?,?,?)",
                   [(r["order_id"], r["customer"], r["status"], r["ordered_at"]) for r in read_csv("orders.csv")])
    db.executemany("INSERT INTO bo_order_lines (order_id, product_id, qty) VALUES (?,?,?)",
                   [(r["order_id"], r["product_id"], int(r["qty"])) for r in read_csv("order_lines.csv")])
    return db


DB = init_db()
app = FastAPI()


def products():
    return [dict(r) for r in DB.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")]


def order_dict(row):
    lines = DB.execute(
        "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l "
        "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ? ORDER BY l.id",
        (row["order_id"],)).fetchall()
    d = dict(row)
    d["lines"] = [dict(l) for l in lines]
    return d


def reject(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


@app.get("/api/users")
def get_users():
    with LOCK:
        return [dict(r) for r in DB.execute("SELECT user_id, name, role FROM bo_users ORDER BY rowid")]


@app.get("/api/products")
def get_products():
    with LOCK:
        return products()


@app.get("/api/orders")
def get_orders():
    with LOCK:
        rows = DB.execute("SELECT order_id, customer, status, ordered_at FROM bo_orders "
                          "ORDER BY ordered_at, order_id").fetchall()
        return [order_dict(r) for r in rows]


@app.post("/api/orders/{order_id}/{action}")
async def post_action(order_id: str, action: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    user_id = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user_id, str):
        return reject(400, "사용자를 확인하세요")
    return do_action(order_id, action, user_id)


def do_action(order_id, action, user_id):
    with LOCK:
        order = DB.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        if order is None:
            return reject(404, "주문을 찾을 수 없습니다")
        user = DB.execute("SELECT * FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
        if user is None:
            return reject(404, "사용자를 찾을 수 없습니다")
        if action not in STATUS_AFTER:
            return reject(404, "없는 동작입니다")
        if action == "refund" and user["role"] != "manager":
            return reject(403, "관리자만 할 수 있습니다")
        if order["status"] not in ALLOWED_FROM[action]:
            return reject(409, "지금 상태에서는 할 수 없습니다")
        lines = DB.execute(
            "SELECT l.product_id, p.name, l.qty, p.stock FROM bo_order_lines l "
            "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ?",
            (order_id,)).fetchall()
        DB.execute("BEGIN IMMEDIATE")
        try:
            if action == "confirm":
                need = {}
                for l in lines:
                    need[l["product_id"]] = need.get(l["product_id"], 0) + l["qty"]
                for l in lines:
                    if l["stock"] < need[l["product_id"]]:
                        DB.execute("ROLLBACK")
                        return reject(409, "재고가 부족합니다: " + l["name"])
                for pid, q in need.items():
                    DB.execute("UPDATE bo_products SET stock = stock - ? WHERE product_id = ?", (q, pid))
            elif action == "cancel" and order["status"] == "confirmed":
                for l in lines:
                    DB.execute("UPDATE bo_products SET stock = stock + ? WHERE product_id = ?",
                               (l["qty"], l["product_id"]))
            DB.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (STATUS_AFTER[action], order_id))
            DB.execute("COMMIT")
        except Exception:
            DB.execute("ROLLBACK")
            raise
        row = DB.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        return {"order": order_dict(row), "products": products()}


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")
