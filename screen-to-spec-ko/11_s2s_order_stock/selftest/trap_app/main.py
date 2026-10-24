# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 흔한 실수만 모았다. T1 · T2 · T6 만 통과해야 채점기가 맞다.
실수: 줄마다 확인하며 바로 차감(부분 차감) · 잠금 없이 읽고 → 잠깐 → 쓰기(동시 확정에 뚫림) · 취소해도 안 되돌림 ·
      환불하면 되돌림 · 권한 검사 없음 · 주문을 본문보다 먼저 찾음(거부 순서)."""
import csv
import os
import sqlite3
import time
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "backoffice.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE bo_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE bo_products(product_id TEXT PRIMARY KEY, name TEXT, stock INTEGER);
    CREATE TABLE bo_orders(order_id TEXT PRIMARY KEY, customer TEXT, status TEXT, ordered_at TEXT);
    CREATE TABLE bo_order_lines(order_id TEXT, product_id TEXT, qty INTEGER);""")
    for name, table, n in (("users.csv", "bo_users", 3), ("products.csv", "bo_products", 3),
                           ("orders.csv", "bo_orders", 4), ("order_lines.csv", "bo_order_lines", 3)):
        with open(os.path.join(SEED, name), encoding="utf-8") as f:
            c.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r for r in csv.reader(f)][1:])
    c.commit()
    c.close()


load()


def con():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def view(c, o):
    return {"order_id": o["order_id"], "customer": o["customer"], "status": o["status"], "ordered_at": o["ordered_at"],
            "lines": [{"product_id": l["product_id"], "name": l["name"], "qty": int(l["qty"])} for l in c.execute(
                "SELECT l.product_id, p.name, l.qty FROM bo_order_lines l JOIN bo_products p ON p.product_id=l.product_id WHERE l.order_id=?",
                (o["order_id"],))]}


def prods(c):
    return [{"product_id": p["product_id"], "name": p["name"], "stock": int(p["stock"])} for p in c.execute("SELECT * FROM bo_products")]


@app.get("/", response_class=HTMLResponse)
def index():
    return "<html><body><h1>주문 관리</h1><p>준비 중</p></body></html>"


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM bo_users")]


@app.get("/api/products")
def products():
    return prods(con())


@app.get("/api/orders")
def orders():
    c = con()
    return [view(c, o) for o in c.execute("SELECT * FROM bo_orders ORDER BY ordered_at").fetchall()]


@app.post("/api/orders/{order_id}/{action}")
def do(order_id: str, action: str, body: dict[str, Any] = Body(default={})):
    c = con()
    o = c.execute("SELECT * FROM bo_orders WHERE order_id=?", (order_id,)).fetchone()
    if not o:
        raise HTTPException(404, "주문이 없습니다")                    # 실수: 본문(400)보다 먼저
    lines = c.execute("SELECT * FROM bo_order_lines WHERE order_id=?", (order_id,)).fetchall()
    if action == "confirm":
        if o["status"] != "placed":
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        for l in lines:                                             # 실수: 줄마다 확인하고 바로 차감 + 잠금 없음
            p = c.execute("SELECT * FROM bo_products WHERE product_id=?", (l["product_id"],)).fetchone()
            time.sleep(0.05)
            if int(p["stock"]) < int(l["qty"]):
                c.commit()
                raise HTTPException(409, "재고가 부족합니다: %s" % p["name"])
            c.execute("UPDATE bo_products SET stock=? WHERE product_id=?", (int(p["stock"]) - int(l["qty"]), l["product_id"]))
        nxt = "confirmed"
    elif action == "ship":
        if o["status"] != "confirmed":
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        nxt = "shipped"
    elif action == "cancel":
        if o["status"] not in ("placed", "confirmed"):
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")
        nxt = "cancelled"                                           # 실수: 재고를 안 되돌림
    elif action == "refund":
        if o["status"] != "shipped":
            raise HTTPException(409, "지금 상태에서는 할 수 없습니다")   # 실수: 권한 검사 없음(상태만)
        for l in lines:                                             # 실수: 환불하면 재고를 되돌림
            c.execute("UPDATE bo_products SET stock=stock+? WHERE product_id=?", (int(l["qty"]), l["product_id"]))
        nxt = "refunded"
    else:
        raise HTTPException(404, "없는 동작입니다")
    c.execute("UPDATE bo_orders SET status=? WHERE order_id=?", (nxt, order_id))
    c.commit()
    return {"order": view(c, c.execute("SELECT * FROM bo_orders WHERE order_id=?", (order_id,)).fetchone()), "products": prods(c)}
