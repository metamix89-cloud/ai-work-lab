import csv
import os
import sqlite3
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "shop.db")
FREE_FROM = 30000
SHIPPING = 3000

app = FastAPI()


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    c = conn()
    c.executescript("""
        CREATE TABLE sh_products(product_id TEXT PRIMARY KEY, name TEXT, price INTEGER,
            sale_price INTEGER, stock INTEGER, max_per_order INTEGER);
        CREATE TABLE sh_options(option_id TEXT PRIMARY KEY, product_id TEXT, label TEXT, extra INTEGER);
        CREATE TABLE sh_carts(cart_id TEXT PRIMARY KEY);
        CREATE TABLE sh_cart_items(item_id INTEGER PRIMARY KEY AUTOINCREMENT, cart_id TEXT,
            product_id TEXT, option_id TEXT, qty INTEGER);
    """)
    with open(os.path.join(BASE, "seed", "products.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            sale = (r["sale_price"] or "").strip()
            c.execute("INSERT INTO sh_products VALUES(?,?,?,?,?,?)",
                      (r["product_id"].strip(), r["name"], int(r["price"]),
                       int(sale) if sale else None, int(r["stock"]), int(r["max_per_order"])))
    with open(os.path.join(BASE, "seed", "options.csv"), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c.execute("INSERT INTO sh_options VALUES(?,?,?,?)",
                      (r["option_id"].strip(), r["product_id"].strip(), r["label"], int(r["extra"])))
    c.commit()
    c.close()


init_db()


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def valid_qty(q, minimum):
    return isinstance(q, int) and not isinstance(q, bool) and q >= minimum


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        return None
    return b if isinstance(b, dict) else None


def cart_view(c, cart_id):
    rows = c.execute(
        """SELECT i.item_id, i.product_id, i.option_id, i.qty, p.name, p.price, p.sale_price,
                  o.label, o.extra
           FROM sh_cart_items i JOIN sh_products p ON p.product_id = i.product_id
           LEFT JOIN sh_options o ON o.option_id = i.option_id
           WHERE i.cart_id = ? ORDER BY i.item_id""", (cart_id,)).fetchall()
    items = []
    subtotal = 0
    for r in rows:
        base = r["sale_price"] if r["sale_price"] is not None else r["price"]
        unit = base + (r["extra"] or 0)
        line = unit * r["qty"]
        subtotal += line
        items.append({"item_id": str(r["item_id"]), "product_id": r["product_id"],
                      "option_id": r["option_id"], "name": r["name"], "label": r["label"],
                      "unit_price": unit, "qty": r["qty"], "line_total": line})
    shipping = 0 if (not items or subtotal >= FREE_FROM) else SHIPPING
    return {"cart_id": cart_id, "items": items, "subtotal": subtotal,
            "shipping": shipping, "total": subtotal + shipping}


def limit_of(p):
    return min(p["stock"], p["max_per_order"])


def limit_msg(p):
    return "최대 %d개까지 담을 수 있습니다" % limit_of(p)


@app.get("/api/products")
def products():
    c = conn()
    opts = {}
    for o in c.execute("SELECT * FROM sh_options ORDER BY rowid"):
        opts.setdefault(o["product_id"], []).append(
            {"option_id": o["option_id"], "label": o["label"], "extra": o["extra"]})
    out = [{"product_id": p["product_id"], "name": p["name"], "price": p["price"],
            "sale_price": p["sale_price"], "stock": p["stock"],
            "max_per_order": p["max_per_order"], "sold_out": p["stock"] <= 0,
            "options": opts.get(p["product_id"], [])}
           for p in c.execute("SELECT * FROM sh_products ORDER BY rowid")]
    c.close()
    return out


@app.post("/api/carts", status_code=201)
def create_cart():
    cid = uuid.uuid4().hex
    c = conn()
    c.execute("INSERT INTO sh_carts VALUES(?)", (cid,))
    c.commit()
    c.close()
    return {"cart_id": cid}


@app.get("/api/carts/{cart_id}")
def get_cart(cart_id: str):
    c = conn()
    try:
        if not c.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone():
            return err(404, "장바구니를 찾을 수 없습니다")
        return cart_view(c, cart_id)
    finally:
        c.close()


@app.post("/api/carts/{cart_id}/items")
async def add_item(cart_id: str, request: Request):
    b = await body_of(request)
    if b is None or not valid_qty(b.get("qty"), 1):
        return err(400, "수량을 확인하세요")
    qty = b["qty"]
    pid, oid = b.get("product_id"), b.get("option_id")
    if not isinstance(pid, str) or (oid is not None and not isinstance(oid, str)):
        return err(400, "옵션을 확인하세요" if isinstance(pid, str) else "상품을 확인하세요")
    c = conn()
    try:
        p = c.execute("SELECT * FROM sh_products WHERE product_id=?", (pid,)).fetchone()
        has_opts = bool(p) and c.execute(
            "SELECT 1 FROM sh_options WHERE product_id=?", (pid,)).fetchone() is not None
        if p:  # R7: 입력 오류(400)가 404 보다 먼저
            if has_opts != (oid is not None):
                return err(400, "옵션을 확인하세요")
            if oid is not None and not c.execute(
                    "SELECT 1 FROM sh_options WHERE option_id=? AND product_id=?", (oid, pid)).fetchone():
                return err(400, "옵션을 확인하세요")
        if not c.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone():
            return err(404, "장바구니를 찾을 수 없습니다")
        if not p:
            return err(404, "상품을 찾을 수 없습니다")
        if p["stock"] <= 0:
            return err(409, "품절된 상품입니다")
        have = c.execute("SELECT COALESCE(SUM(qty),0) FROM sh_cart_items WHERE cart_id=? AND product_id=?",
                         (cart_id, pid)).fetchone()[0]
        if have + qty > limit_of(p):
            return err(409, limit_msg(p))
        row = c.execute("SELECT item_id FROM sh_cart_items WHERE cart_id=? AND product_id=? AND option_id IS ?",
                        (cart_id, pid, oid)).fetchone()
        if row:
            c.execute("UPDATE sh_cart_items SET qty = qty + ? WHERE item_id=?", (qty, row["item_id"]))
        else:
            c.execute("INSERT INTO sh_cart_items(cart_id,product_id,option_id,qty) VALUES(?,?,?,?)",
                      (cart_id, pid, oid, qty))
        c.commit()
        return JSONResponse(cart_view(c, cart_id), status_code=201)
    finally:
        c.close()


@app.put("/api/carts/{cart_id}/items/{item_id}")
async def update_item(cart_id: str, item_id: str, request: Request):
    b = await body_of(request)
    if b is None or not valid_qty(b.get("qty"), 0):
        return err(400, "수량을 확인하세요")
    qty = b["qty"]
    c = conn()
    try:
        if not c.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone():
            return err(404, "장바구니를 찾을 수 없습니다")
        it = c.execute("SELECT * FROM sh_cart_items WHERE cart_id=? AND item_id=?",
                       (cart_id, item_id)).fetchone() if item_id.isdigit() else None
        if not it:
            return err(404, "장바구니 줄을 찾을 수 없습니다")
        if qty == 0:
            c.execute("DELETE FROM sh_cart_items WHERE item_id=?", (it["item_id"],))
        else:
            p = c.execute("SELECT * FROM sh_products WHERE product_id=?", (it["product_id"],)).fetchone()
            others = c.execute(
                "SELECT COALESCE(SUM(qty),0) FROM sh_cart_items WHERE cart_id=? AND product_id=? AND item_id<>?",
                (cart_id, it["product_id"], it["item_id"])).fetchone()[0]
            if others + qty > limit_of(p):
                return err(409, limit_msg(p))
            c.execute("UPDATE sh_cart_items SET qty=? WHERE item_id=?", (qty, it["item_id"]))
        c.commit()
        return cart_view(c, cart_id)
    finally:
        c.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
