import csv
import json
import os
import sqlite3
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "backoffice.db")
LOCK = threading.Lock()  # 읽고 → 확인하고 → 쓰기 를 한 번에 한 요청씩

NEXT = {"confirm": ("placed", "confirmed"), "ship": ("confirmed", "shipped"),
        "refund": ("shipped", "refunded")}


def connect():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    con = connect()
    con.executescript("""
        CREATE TABLE bo_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE bo_products (product_id TEXT PRIMARY KEY, name TEXT, stock INTEGER CHECK (stock >= 0));
        CREATE TABLE bo_orders (order_id TEXT PRIMARY KEY, customer TEXT, status TEXT, ordered_at TEXT);
        CREATE TABLE bo_order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, product_id TEXT, qty INTEGER);
    """)
    con.executemany("INSERT INTO bo_users VALUES (?,?,?)",
                    [(r["user_id"], r["name"], r["role"]) for r in read_csv("users.csv")])
    con.executemany("INSERT INTO bo_products VALUES (?,?,?)",
                    [(r["product_id"], r["name"], int(r["stock"])) for r in read_csv("products.csv")])
    con.executemany("INSERT INTO bo_orders VALUES (?,?,?,?)",
                    [(r["order_id"], r["customer"], r["status"], r["ordered_at"]) for r in read_csv("orders.csv")])
    con.executemany("INSERT INTO bo_order_lines (order_id, product_id, qty) VALUES (?,?,?)",
                    [(r["order_id"], r["product_id"], int(r["qty"])) for r in read_csv("order_lines.csv")])
    con.commit()
    con.close()


init_db()
app = FastAPI()


def products(con):
    return [dict(r) for r in con.execute("SELECT product_id, name, stock FROM bo_products ORDER BY product_id")]


def order_dict(con, row):
    lines = con.execute(
        "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l "
        "LEFT JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ? ORDER BY l.id",
        (row["order_id"],)).fetchall()
    d = dict(row)
    d["lines"] = [dict(l) for l in lines]
    return d


def reject(code, detail):
    return JSONResponse({"detail": detail}, status_code=code)


@app.get("/api/users")
def get_users():
    con = connect()
    try:
        return [dict(r) for r in con.execute("SELECT user_id, name, role FROM bo_users ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/products")
def get_products():
    con = connect()
    try:
        return products(con)
    finally:
        con.close()


@app.get("/api/orders")
def get_orders():
    con = connect()
    try:
        rows = con.execute("SELECT * FROM bo_orders ORDER BY ordered_at, order_id").fetchall()
        return [order_dict(con, r) for r in rows]
    finally:
        con.close()


@app.post("/api/orders/{order_id}/{action}")
async def do_action(order_id: str, action: str, request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    user = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user, str):
        return reject(400, "사용자를 확인하세요")
    return run_action(order_id, action, user)


def run_action(order_id, action, user_id):
    with LOCK:
        con = connect()
        try:
            order = con.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
            if action not in ("confirm", "ship", "cancel", "refund") or order is None:
                return reject(404, "없는 주문 또는 동작입니다")
            user = con.execute("SELECT * FROM bo_users WHERE user_id = ?", (user_id,)).fetchone()
            if user is None:
                return reject(404, "없는 사용자입니다")
            if action == "refund" and user["role"] != "manager":
                return reject(403, "관리자만 할 수 있습니다")
            status = order["status"]
            if action == "cancel":
                ok, new = status in ("placed", "confirmed"), "cancelled"
            else:
                ok, new = status == NEXT[action][0], NEXT[action][1]
            if not ok:
                return reject(409, "지금 상태에서는 할 수 없습니다")
            lines = con.execute(
                "SELECT l.product_id, l.qty, p.name, p.stock FROM bo_order_lines l "
                "JOIN bo_products p ON p.product_id = l.product_id WHERE l.order_id = ?",
                (order_id,)).fetchall()
            con.execute("BEGIN IMMEDIATE")
            if action == "confirm":
                need = {}
                for l in lines:
                    need[l["product_id"]] = need.get(l["product_id"], 0) + l["qty"]
                for l in lines:
                    if l["stock"] < need[l["product_id"]]:
                        con.rollback()
                        return reject(409, "재고가 부족합니다: " + l["name"])
                for pid, q in need.items():
                    con.execute("UPDATE bo_products SET stock = stock - ? WHERE product_id = ?", (q, pid))
            elif action == "cancel" and status == "confirmed":
                for l in lines:
                    con.execute("UPDATE bo_products SET stock = stock + ? WHERE product_id = ?",
                                (l["qty"], l["product_id"]))
            con.execute("UPDATE bo_orders SET status = ? WHERE order_id = ?", (new, order_id))
            con.commit()
            row = con.execute("SELECT * FROM bo_orders WHERE order_id = ?", (order_id,)).fetchone()
            return {"order": order_dict(con, row), "products": products(con)}
        finally:
            con.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
