# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R7 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import os
import sqlite3
import uuid
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "shop.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE sh_products(product_id TEXT PRIMARY KEY, name TEXT, price INTEGER, sale_price TEXT, stock INTEGER, max_per_order INTEGER);
    CREATE TABLE sh_options(option_id TEXT PRIMARY KEY, product_id TEXT, label TEXT, extra INTEGER);
    CREATE TABLE sh_carts(cart_id TEXT PRIMARY KEY);
    CREATE TABLE sh_cart_items(item_id TEXT PRIMARY KEY, cart_id TEXT, product_id TEXT, option_id TEXT, qty INTEGER);""")
    for name, table, n in (("products.csv", "sh_products", 6), ("options.csv", "sh_options", 4)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
            con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def sale(r):
    return int(r["sale_price"]) if str(r["sale_price"] or "").strip() else None


def unit_price(c, pid, oid):
    p = c.execute("SELECT * FROM sh_products WHERE product_id=?", (pid,)).fetchone()
    base = sale(p) if sale(p) is not None else int(p["price"])
    extra = int(c.execute("SELECT extra FROM sh_options WHERE option_id=?", (oid,)).fetchone()["extra"]) if oid else 0
    return base + extra


def cart_view(c, cid):
    items = []
    for it in c.execute("""SELECT i.*, p.name, o.label FROM sh_cart_items i JOIN sh_products p ON p.product_id=i.product_id
                           LEFT JOIN sh_options o ON o.option_id=i.option_id WHERE cart_id=? ORDER BY i.rowid""", (cid,)).fetchall():
        up = unit_price(c, it["product_id"], it["option_id"])
        items.append({"item_id": it["item_id"], "product_id": it["product_id"], "option_id": it["option_id"], "name": it["name"],
                      "label": it["label"], "unit_price": up, "qty": it["qty"], "line_total": up * it["qty"]})
    sub = sum(i["line_total"] for i in items)
    ship = 0 if (sub == 0 or sub >= 30000) else 3000
    return {"cart_id": cid, "items": items, "subtotal": sub, "shipping": ship, "total": sub + ship}


def limit(c, pid):
    p = c.execute("SELECT stock, max_per_order FROM sh_products WHERE product_id=?", (pid,)).fetchone()
    return min(int(p["stock"]), int(p["max_per_order"]))


def in_cart(c, cid, pid, except_item=None):
    return sum(r["qty"] for r in c.execute("SELECT item_id, qty FROM sh_cart_items WHERE cart_id=? AND product_id=?", (cid, pid))
               if r["item_id"] != except_item)


def is_int(v, lo):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/products")
def products():
    c = con()
    out = []
    for p in c.execute("SELECT * FROM sh_products"):
        out.append({"product_id": p["product_id"], "name": p["name"], "price": int(p["price"]), "sale_price": sale(p), "stock": int(p["stock"]),
                    "max_per_order": int(p["max_per_order"]), "sold_out": int(p["stock"]) == 0,
                    "options": [{"option_id": o["option_id"], "label": o["label"], "extra": int(o["extra"])}
                                for o in c.execute("SELECT * FROM sh_options WHERE product_id=?", (p["product_id"],))]})
    return out


@app.post("/api/carts", status_code=201)
def new_cart():
    c = con()
    cid = uuid.uuid4().hex[:12]
    c.execute("INSERT INTO sh_carts VALUES (?)", (cid,))
    c.commit()
    return {"cart_id": cid}


@app.get("/api/carts/{cid}")
def get_cart(cid: str):
    c = con()
    if not c.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cid,)).fetchone():
        raise HTTPException(404, "장바구니가 없습니다")
    return cart_view(c, cid)


@app.post("/api/carts/{cid}/items", status_code=201)
def add_item(cid: str, body: dict[str, Any] = Body(...)):
    c = con()
    pid, oid, qty = body.get("product_id"), body.get("option_id"), body.get("qty")
    if not isinstance(pid, str) or not is_int(qty, 1):
        raise HTTPException(400, "수량을 확인하세요")
    if not c.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cid,)).fetchone():
        raise HTTPException(404, "장바구니가 없습니다")
    p = c.execute("SELECT * FROM sh_products WHERE product_id=?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "상품이 없습니다")
    opts = [o["option_id"] for o in c.execute("SELECT option_id FROM sh_options WHERE product_id=?", (pid,))]
    if (opts and oid not in opts) or (not opts and oid not in (None, "")):
        raise HTTPException(400, "옵션을 확인하세요")
    oid = oid or None
    if int(p["stock"]) == 0:
        raise HTTPException(409, "품절된 상품입니다")
    lim = limit(c, pid)
    if in_cart(c, cid, pid) + qty > lim:
        raise HTTPException(409, "최대 %d개까지 담을 수 있습니다" % lim)
    same = c.execute("SELECT item_id FROM sh_cart_items WHERE cart_id=? AND product_id=? AND option_id IS ?", (cid, pid, oid)).fetchone()
    if same:
        c.execute("UPDATE sh_cart_items SET qty=qty+? WHERE item_id=?", (qty, same["item_id"]))
    else:
        c.execute("INSERT INTO sh_cart_items VALUES (?,?,?,?,?)", (uuid.uuid4().hex[:8], cid, pid, oid, qty))
    c.commit()
    return cart_view(c, cid)


@app.put("/api/carts/{cid}/items/{item_id}")
def set_qty(cid: str, item_id: str, body: dict[str, Any] = Body(...)):
    c = con()
    qty = body.get("qty")
    if not is_int(qty, 0):
        raise HTTPException(400, "수량을 확인하세요")
    it = c.execute("SELECT * FROM sh_cart_items WHERE cart_id=? AND item_id=?", (cid, item_id)).fetchone()
    if not it:
        raise HTTPException(404, "장바구니 줄이 없습니다")
    if qty == 0:
        c.execute("DELETE FROM sh_cart_items WHERE item_id=?", (item_id,))
    else:
        lim = limit(c, it["product_id"])
        if in_cart(c, cid, it["product_id"], except_item=item_id) + qty > lim:
            raise HTTPException(409, "최대 %d개까지 담을 수 있습니다" % lim)
        c.execute("UPDATE sh_cart_items SET qty=? WHERE item_id=?", (qty, item_id))
    c.commit()
    return cart_view(c, cid)
