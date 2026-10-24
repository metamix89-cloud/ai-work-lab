import csv
import json
import sqlite3
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "backoffice.db"
LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    stock INTEGER NOT NULL CHECK (stock >= 0));
CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT NOT NULL,
    status TEXT NOT NULL, ordered_at TEXT NOT NULL);
CREATE TABLE bo_order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL,
    product_id TEXT NOT NULL, qty INTEGER NOT NULL);
"""

# action -> (허용되는 현재 상태, 다음 상태)
ACTIONS = {
    "confirm": (("placed",), "confirmed"),
    "ship": (("confirmed",), "shipped"),
    "cancel": (("placed", "confirmed"), "cancelled"),
    "refund": (("shipped",), "refunded"),
}


def read_csv(name):
    with open(BASE / "seed" / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO bo_users VALUES (?,?,?)",
                     [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    conn.executemany("INSERT INTO bo_products VALUES (?,?,?)",
                     [(r["product_id"], r["name"], int(r["stock"])) for r in read_csv("products.csv")])
    conn.executemany("INSERT INTO bo_orders VALUES (?,?,?,?)",
                     [(r["order_id"], r["customer"], r["status"], r["ordered_at"]) for r in read_csv("orders.csv")])
    conn.executemany("INSERT INTO bo_order_lines (order_id, product_id, qty) VALUES (?,?,?)",
                     [(r["order_id"], r["product_id"], int(r["qty"])) for r in read_csv("order_lines.csv")])
    conn.commit()
    return conn


DB = init_db()
app = FastAPI()


def reject(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def products():
    rows = DB.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")
    return [dict(r) for r in rows]


def order_dict(row):
    lines = DB.execute(
        "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l "
        "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ? ORDER BY l.id",
        (row["order_id"],))
    return {"order_id": row["order_id"], "customer": row["customer"], "status": row["status"],
            "ordered_at": row["ordered_at"], "lines": [dict(l) for l in lines]}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


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
    # 400: 본문만 보면 아는 것
    try:
        body = json.loads((await request.body()) or b"")
    except ValueError:
        body = None
    user_id = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user_id, str):
        return reject(400, "사용자를 확인하세요")

    with LOCK:
        # 404: 없는 주문 · 사용자 · 동작
        order = DB.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        if order is None:
            return reject(404, "주문을 찾을 수 없습니다")
        user = DB.execute("SELECT * FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
        if user is None:
            return reject(404, "사용자를 찾을 수 없습니다")
        if action not in ACTIONS:
            return reject(404, "알 수 없는 동작입니다")
        # 403: 권한
        if action == "refund" and user["role"] != "manager":
            return reject(403, "관리자만 할 수 있습니다")
        # 409: 상태 · 재고
        allowed, nxt = ACTIONS[action]
        if order["status"] not in allowed:
            return reject(409, "지금 상태에서는 할 수 없습니다")
        lines = DB.execute(
            "SELECT l.product_id, l.qty, p.name, p.stock FROM bo_order_lines l "
            "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ?",
            (order_id,)).fetchall()
        try:
            if action == "confirm":
                need = {}
                for l in lines:
                    need[l["product_id"]] = need.get(l["product_id"], 0) + l["qty"]
                for l in lines:
                    if l["stock"] < need[l["product_id"]]:
                        return reject(409, f"재고가 부족합니다: {l['name']}")
                for l in lines:
                    DB.execute("UPDATE bo_products SET stock = stock - ? WHERE product_id = ?",
                               (l["qty"], l["product_id"]))
            elif action == "cancel" and order["status"] == "confirmed":
                for l in lines:
                    DB.execute("UPDATE bo_products SET stock = stock + ? WHERE product_id = ?",
                               (l["qty"], l["product_id"]))
            DB.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (nxt, order_id))
            DB.commit()
        except Exception:
            DB.rollback()
            raise
        updated = DB.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
        return {"order": order_dict(updated), "products": products()}
