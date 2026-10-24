import csv
import os
import sqlite3
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "backoffice.db"
LOCK = threading.Lock()

ACTIONS = {
    "confirm": ({"placed"}, "confirmed"),
    "ship": ({"confirmed"}, "shipped"),
    "cancel": ({"placed", "confirmed"}, "cancelled"),
    "refund": ({"shipped"}, "refunded"),
}


def read_csv(name):
    with open(BASE / "seed" / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
        CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            stock INTEGER NOT NULL CHECK (stock >= 0));
        CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT NOT NULL,
            status TEXT NOT NULL, ordered_at TEXT NOT NULL);
        CREATE TABLE bo_order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL,
            product_id TEXT NOT NULL, qty INTEGER NOT NULL);
        """
    )
    db.executemany("INSERT INTO bo_users VALUES (?,?,?)",
                   [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    db.executemany("INSERT INTO bo_products VALUES (?,?,?)",
                   [(r["product_id"], r["name"], int(r["stock"])) for r in read_csv("products.csv")])
    db.executemany("INSERT INTO bo_orders VALUES (?,?,?,?)",
                   [(r["order_id"], r["customer"], r["status"], r["ordered_at"]) for r in read_csv("orders.csv")])
    db.executemany("INSERT INTO bo_order_lines (order_id, product_id, qty) VALUES (?,?,?)",
                   [(r["order_id"], r["product_id"], int(r["qty"])) for r in read_csv("order_lines.csv")])
    db.commit()
    return db


DB = init_db()
app = FastAPI()


def products():
    rows = DB.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id").fetchall()
    return [dict(r) for r in rows]


def order_dict(row):
    lines = DB.execute(
        "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l "
        "LEFT JOIN bo_products p ON p.product_id = l.product_id "
        "WHERE l.order_id = ? ORDER BY l.id", (row["order_id"],)).fetchall()
    return {
        "order_id": row["order_id"],
        "customer": row["customer"],
        "status": row["status"],
        "ordered_at": row["ordered_at"],
        "lines": [dict(l) for l in lines],
    }


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
        rows = DB.execute("SELECT * FROM bo_orders ORDER BY ordered_at, order_id").fetchall()
        return [order_dict(r) for r in rows]


@app.post("/api/orders/{order_id}/{action}")
async def do_action(order_id: str, action: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    user_id = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user_id, str):
        return reject(400, "사용자를 확인하세요")
    return run_action(order_id, action, user_id)


def run_action(order_id, action, user_id):
    with LOCK:
        order = DB.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        user = DB.execute("SELECT * FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
        if order is None:
            return reject(404, "주문을 찾을 수 없습니다")
        if user is None:
            return reject(404, "사용자를 찾을 수 없습니다")
        if action not in ACTIONS:
            return reject(404, "알 수 없는 동작입니다")
        if action == "refund" and user["role"] != "manager":
            return reject(403, "관리자만 할 수 있습니다")
        allowed, new_status = ACTIONS[action]
        if order["status"] not in allowed:
            return reject(409, "지금 상태에서는 할 수 없습니다")
        try:
            DB.execute("BEGIN")
            need = DB.execute(
                "SELECT product_id, SUM(qty) AS qty FROM bo_order_lines WHERE order_id = ? GROUP BY product_id",
                (order_id,)).fetchall()
            if action == "confirm":
                for n in need:
                    p = DB.execute("SELECT name, stock FROM bo_products WHERE product_id = ?",
                                   (n["product_id"],)).fetchone()
                    if p is None or p["stock"] < n["qty"]:
                        DB.execute("ROLLBACK")
                        return reject(409, "재고가 부족합니다: " + (p["name"] if p else n["product_id"]))
                for n in need:
                    DB.execute("UPDATE bo_products SET stock = stock - ? WHERE product_id = ?",
                               (n["qty"], n["product_id"]))
            elif action == "cancel" and order["status"] == "confirmed":
                for n in need:
                    DB.execute("UPDATE bo_products SET stock = stock + ? WHERE product_id = ?",
                               (n["qty"], n["product_id"]))
            DB.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (new_status, order_id))
            DB.execute("COMMIT")
        except Exception:
            if DB.in_transaction:
                DB.execute("ROLLBACK")
            raise
        row = DB.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        return {"order": order_dict(row), "products": products()}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
