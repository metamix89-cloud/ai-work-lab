# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R8 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
동시 확정(R5): 상태 · 재고를 바꾸는 동작은 잠금 하나로 한 번에 하나씩 — 읽고 → 확인하고 → 쓰기 사이에 다른 요청이 끼지 못한다."""
import csv
import os
import sqlite3
import threading
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "backoffice.db")
LOCK = threading.Lock()
app = FastAPI()

MOVES = {"confirm": ({"placed"}, "confirmed"), "ship": ({"confirmed"}, "shipped"),
         "cancel": ({"placed", "confirmed"}, "cancelled"), "refund": ({"shipped"}, "refunded")}


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE bo_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE bo_products(product_id TEXT PRIMARY KEY, name TEXT, stock INTEGER CHECK (stock >= 0));
    CREATE TABLE bo_orders(order_id TEXT PRIMARY KEY, customer TEXT, status TEXT, ordered_at TEXT);
    CREATE TABLE bo_order_lines(order_id TEXT, product_id TEXT, qty INTEGER);""")
    for name, table, n in (("users.csv", "bo_users", 3), ("products.csv", "bo_products", 3),
                           ("orders.csv", "bo_orders", 4), ("order_lines.csv", "bo_order_lines", 3)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
            con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def order_view(c, o):
    lines = [{"product_id": l["product_id"], "name": l["name"], "qty": int(l["qty"])}
             for l in c.execute("""SELECT l.product_id, p.name, l.qty FROM bo_order_lines l JOIN bo_products p ON p.product_id=l.product_id
                                   WHERE l.order_id=? ORDER BY l.rowid""", (o["order_id"],))]
    return {"order_id": o["order_id"], "customer": o["customer"], "status": o["status"], "ordered_at": o["ordered_at"], "lines": lines}


def products_view(c):
    return [{"product_id": p["product_id"], "name": p["name"], "stock": int(p["stock"])} for p in c.execute("SELECT * FROM bo_products ORDER BY product_id")]


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM bo_users ORDER BY rowid")]


@app.get("/api/products")
def products():
    return products_view(con())


@app.get("/api/orders")
def orders():
    c = con()
    return [order_view(c, o) for o in c.execute("SELECT * FROM bo_orders ORDER BY ordered_at, order_id").fetchall()]


@app.post("/api/orders/{order_id}/{action}")
def do(order_id: str, action: str, body: dict[str, Any] = Body(default={})):
    user = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user, str) or not user:
        raise HTTPException(400, "사용자를 확인하세요")
    with LOCK:
        c = con()
        o = c.execute("SELECT * FROM bo_orders WHERE order_id=?", (order_id,)).fetchone()
        if not o:
            raise HTTPException(404, "주문이 없습니다")
        u = c.execute("SELECT * FROM bo_users WHERE user_id=?", (user,)).fetchone()
        if not u:
            raise HTTPException(404, "사용자가 없습니다")
        if action not in MOVES:
            raise HTTPException(404, "없는 동작입니다")
        if action == "refund" and u["role"] != "manager":
            raise HTTPException(403, "관리자만 할 수 있습니다")
        allowed, nxt = MOVES[action]
        if o["status"] not in allowed:
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        # 같은 상품 줄이 여럿이면 합쳐서 본다 — 줄마다 따로 비교하면 재고 3 에 2개 + 2개가 둘 다 통과해 -1 이 된다
        # (처음 판은 그랬다. 11편 B · C 여섯이 모두 합쳐서 막는 것을 보고 고침). 없는 상품을 가리키는 줄은 LEFT JOIN 으로 잡아 409.
        lines = c.execute("""SELECT l.product_id, SUM(l.qty) AS qty, p.name, p.stock FROM bo_order_lines l LEFT JOIN bo_products p ON p.product_id=l.product_id
                             WHERE l.order_id=? GROUP BY l.product_id""", (order_id,)).fetchall()
        if action == "confirm" and any(l["name"] is None for l in lines):
            raise HTTPException(409, "없는 상품이 있는 주문입니다")
        if action == "confirm":
            for l in lines:
                if int(l["stock"]) < int(l["qty"]):
                    raise HTTPException(409, "재고가 부족합니다: %s" % l["name"])
            for l in lines:
                c.execute("UPDATE bo_products SET stock=stock-? WHERE product_id=?", (int(l["qty"]), l["product_id"]))
        elif action == "cancel" and o["status"] == "confirmed":
            for l in lines:
                c.execute("UPDATE bo_products SET stock=stock+? WHERE product_id=?", (int(l["qty"]), l["product_id"]))
        c.execute("UPDATE bo_orders SET status=? WHERE order_id=?", (nxt, order_id))
        c.commit()
        o = c.execute("SELECT * FROM bo_orders WHERE order_id=?", (order_id,)).fetchone()
        return {"order": order_view(c, o), "products": products_view(c)}
