import csv
import os
import sqlite3
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "shop.db")
FREE_SHIPPING_FROM = 30000
SHIPPING_FEE = 3000


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
        CREATE TABLE sh_products(product_id TEXT PRIMARY KEY, name TEXT, price INTEGER,
            sale_price INTEGER, stock INTEGER, max_per_order INTEGER, ord INTEGER);
        CREATE TABLE sh_options(option_id TEXT PRIMARY KEY, product_id TEXT, label TEXT,
            extra INTEGER, ord INTEGER);
        CREATE TABLE sh_carts(cart_id TEXT PRIMARY KEY);
        CREATE TABLE sh_cart_items(item_id INTEGER PRIMARY KEY AUTOINCREMENT, cart_id TEXT,
            product_id TEXT, option_id TEXT, qty INTEGER);
    """)
    with open(os.path.join(BASE, "seed", "products.csv"), encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            sp = (r["sale_price"] or "").strip()
            con.execute("INSERT INTO sh_products VALUES(?,?,?,?,?,?,?)",
                        (r["product_id"].strip(), r["name"], int(r["price"]), int(sp) if sp else None,
                         int(r["stock"]), int(r["max_per_order"]), i))
    with open(os.path.join(BASE, "seed", "options.csv"), encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            con.execute("INSERT INTO sh_options VALUES(?,?,?,?,?)",
                        (r["option_id"].strip(), r["product_id"].strip(), r["label"], int(r["extra"] or 0), i))
    con.commit()
    con.close()


init_db()
app = FastAPI()


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def valid_qty(v, minimum):
    return isinstance(v, int) and not isinstance(v, bool) and v >= minimum


def cart_json(con, cart_id):
    rows = con.execute("""
        SELECT i.item_id, i.product_id, i.option_id, i.qty, p.name, p.price, p.sale_price,
               o.label, o.extra
        FROM sh_cart_items i JOIN sh_products p ON p.product_id = i.product_id
        LEFT JOIN sh_options o ON o.option_id = i.option_id
        WHERE i.cart_id = ? ORDER BY i.item_id""", (cart_id,)).fetchall()
    items, subtotal = [], 0
    for r in rows:
        base = r["sale_price"] if r["sale_price"] is not None else r["price"]
        unit = base + (r["extra"] or 0)
        line = unit * r["qty"]
        subtotal += line
        items.append({"item_id": str(r["item_id"]), "product_id": r["product_id"],
                      "option_id": r["option_id"], "name": r["name"], "label": r["label"],
                      "unit_price": unit, "qty": r["qty"], "line_total": line})
    shipping = 0 if not items or subtotal >= FREE_SHIPPING_FROM else SHIPPING_FEE
    return {"cart_id": cart_id, "items": items, "subtotal": subtotal,
            "shipping": shipping, "total": subtotal + shipping}


def limit_of(p):
    return min(p["stock"], p["max_per_order"])


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return None
    return b if isinstance(b, dict) else None


@app.get("/api/products")
def products():
    con = db()
    out = []
    for p in con.execute("SELECT * FROM sh_products ORDER BY ord"):
        opts = con.execute("SELECT option_id, label, extra FROM sh_options WHERE product_id=? ORDER BY ord",
                           (p["product_id"],)).fetchall()
        out.append({"product_id": p["product_id"], "name": p["name"], "price": p["price"],
                    "sale_price": p["sale_price"], "stock": p["stock"],
                    "max_per_order": p["max_per_order"], "sold_out": p["stock"] <= 0,
                    "options": [dict(o) for o in opts]})
    con.close()
    return out


@app.post("/api/carts", status_code=201)
def create_cart():
    cid = uuid.uuid4().hex
    con = db()
    con.execute("INSERT INTO sh_carts VALUES(?)", (cid,))
    con.commit()
    con.close()
    return {"cart_id": cid}


@app.get("/api/carts/{cart_id}")
def get_cart(cart_id: str):
    con = db()
    try:
        if not con.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone():
            return err(404, "장바구니를 찾을 수 없습니다")
        return cart_json(con, cart_id)
    finally:
        con.close()


@app.post("/api/carts/{cart_id}/items")
async def add_item(cart_id: str, request: Request):
    b = await body_of(request)
    if b is None or not valid_qty(b.get("qty"), 1):
        return err(400, "수량을 확인하세요")
    pid, oid, qty = b.get("product_id"), b.get("option_id"), b["qty"]
    if not isinstance(pid, str) or (oid is not None and not isinstance(oid, str)):
        return err(400, "옵션을 확인하세요" if isinstance(pid, str) else "상품을 확인하세요")
    con = db()
    try:
        if not con.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone():
            return err(404, "장바구니를 찾을 수 없습니다")
        p = con.execute("SELECT * FROM sh_products WHERE product_id=?", (pid,)).fetchone()
        if not p:
            return err(404, "상품을 찾을 수 없습니다")
        has_opts = con.execute("SELECT 1 FROM sh_options WHERE product_id=?", (pid,)).fetchone()
        if has_opts:
            if oid is None or not con.execute("SELECT 1 FROM sh_options WHERE option_id=? AND product_id=?",
                                              (oid, pid)).fetchone():
                return err(400, "옵션을 확인하세요")
        elif oid is not None:
            return err(400, "옵션을 확인하세요")
        if p["stock"] <= 0:
            return err(409, "품절된 상품입니다")
        have = con.execute("SELECT COALESCE(SUM(qty),0) FROM sh_cart_items WHERE cart_id=? AND product_id=?",
                           (cart_id, pid)).fetchone()[0]
        lim = limit_of(p)
        if have + qty > lim:
            return err(409, "최대 %d개까지 담을 수 있습니다" % lim)
        same = con.execute("SELECT item_id FROM sh_cart_items WHERE cart_id=? AND product_id=? AND option_id IS ?",
                           (cart_id, pid, oid)).fetchone()
        if same:
            con.execute("UPDATE sh_cart_items SET qty = qty + ? WHERE item_id=?", (qty, same["item_id"]))
        else:
            con.execute("INSERT INTO sh_cart_items(cart_id, product_id, option_id, qty) VALUES(?,?,?,?)",
                        (cart_id, pid, oid, qty))
        con.commit()
        return JSONResponse(cart_json(con, cart_id), status_code=201)
    finally:
        con.close()


@app.put("/api/carts/{cart_id}/items/{item_id}")
async def update_item(cart_id: str, item_id: str, request: Request):
    b = await body_of(request)
    if b is None or not valid_qty(b.get("qty"), 0):
        return err(400, "수량을 확인하세요")
    qty = b["qty"]
    con = db()
    try:
        if not con.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone():
            return err(404, "장바구니를 찾을 수 없습니다")
        it = None
        if item_id.isdigit():
            it = con.execute("SELECT * FROM sh_cart_items WHERE item_id=? AND cart_id=?",
                             (int(item_id), cart_id)).fetchone()
        if not it:
            return err(404, "장바구니 줄을 찾을 수 없습니다")
        if qty == 0:
            con.execute("DELETE FROM sh_cart_items WHERE item_id=?", (it["item_id"],))
        else:
            p = con.execute("SELECT * FROM sh_products WHERE product_id=?", (it["product_id"],)).fetchone()
            others = con.execute("""SELECT COALESCE(SUM(qty),0) FROM sh_cart_items
                                    WHERE cart_id=? AND product_id=? AND item_id<>?""",
                                 (cart_id, it["product_id"], it["item_id"])).fetchone()[0]
            lim = limit_of(p)
            if others + qty > lim:
                return err(409, "최대 %d개까지 담을 수 있습니다" % lim)
            con.execute("UPDATE sh_cart_items SET qty=? WHERE item_id=?", (qty, it["item_id"]))
        con.commit()
        return cart_json(con, cart_id)
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
