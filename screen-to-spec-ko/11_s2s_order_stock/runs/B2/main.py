import csv
import os
import sqlite3
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "backoffice.db"

app = FastAPI()
lock = threading.RLock()

SCHEMA = """
CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
  stock INTEGER NOT NULL CHECK (stock >= 0));
CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT NOT NULL,
  status TEXT NOT NULL, ordered_at TEXT NOT NULL);
CREATE TABLE bo_order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL,
  product_id TEXT NOT NULL, qty INTEGER NOT NULL CHECK (qty >= 1));
"""


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(str(DB_PATH) + suffix)
        except FileNotFoundError:
            pass
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("BEGIN")
    for r in read_csv("users.csv"):
        conn.execute("INSERT INTO bo_users VALUES (?,?,?)", (r["user_id"], r["name"], r["role"]))
    for r in read_csv("products.csv"):
        conn.execute("INSERT INTO bo_products VALUES (?,?,?)", (r["product_id"], r["name"], int(r["stock"])))
    for r in read_csv("orders.csv"):
        conn.execute("INSERT INTO bo_orders VALUES (?,?,?,?)",
                     (r["order_id"], r["customer"], r["status"], r["ordered_at"]))
    for r in read_csv("order_lines.csv"):
        conn.execute("INSERT INTO bo_order_lines (order_id, product_id, qty) VALUES (?,?,?)",
                     (r["order_id"], r["product_id"], int(r["qty"])))
    conn.execute("COMMIT")
    return conn


db = init_db()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def products():
    return [dict(r) for r in db.execute(
        "SELECT product_id, name, stock FROM bo_products ORDER BY product_id")]


def order_dict(row):
    lines = [dict(l) for l in db.execute(
        "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l "
        "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ? ORDER BY l.id",
        (row["order_id"],))]
    return {"order_id": row["order_id"], "customer": row["customer"], "status": row["status"],
            "ordered_at": row["ordered_at"], "lines": lines}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


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
        rows = db.execute("SELECT * FROM bo_orders ORDER BY ordered_at, order_id").fetchall()
        return [order_dict(r) for r in rows]


TRANSITIONS = {  # action: (allowed from, to)
    "confirm": ({"placed"}, "confirmed"),
    "ship": ({"confirmed"}, "shipped"),
    "cancel": ({"placed", "confirmed"}, "cancelled"),
    "refund": ({"shipped"}, "refunded"),
}


@app.post("/api/orders/{order_id}/{action}")
async def do_action(order_id: str, action: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None
    user_id = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user_id, str):
        return err(400, "사용자를 확인하세요")
    with lock:
        order = db.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        user = db.execute("SELECT * FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
        if order is None or user is None or action not in TRANSITIONS:
            return err(404, "찾을 수 없습니다")
        if action == "refund" and user["role"] != "manager":
            return err(403, "관리자만 할 수 있습니다")
        allowed, new_status = TRANSITIONS[action]
        if order["status"] not in allowed:
            return err(409, "지금 상태에서는 할 수 없습니다")
        lines = db.execute(
            "SELECT l.product_id, l.qty, p.name, p.stock FROM bo_order_lines l "
            "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ?",
            (order_id,)).fetchall()
        db.execute("BEGIN")
        try:
            if action == "confirm":
                need = {}
                for l in lines:
                    need[l["product_id"]] = need.get(l["product_id"], 0) + l["qty"]
                for l in lines:
                    if l["stock"] < need[l["product_id"]]:
                        db.execute("ROLLBACK")
                        return err(409, f"재고가 부족합니다: {l['name']}")
                for l in lines:
                    db.execute("UPDATE bo_products SET stock = stock - ? WHERE product_id = ?",
                               (l["qty"], l["product_id"]))
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
