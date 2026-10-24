import csv
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "shop.db")
FREE_FROM = 30000
SHIPPING = 3000


def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def to_int(v):
    v = (v or "").strip()
    return int(v) if v else None


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    con = connect()
    con.executescript("""
        CREATE TABLE sh_products(product_id TEXT PRIMARY KEY, name TEXT, price INTEGER,
            sale_price INTEGER, stock INTEGER, max_per_order INTEGER, seq INTEGER);
        CREATE TABLE sh_options(option_id TEXT PRIMARY KEY, product_id TEXT, label TEXT,
            extra INTEGER, seq INTEGER);
        CREATE TABLE sh_carts(cart_id TEXT PRIMARY KEY);
        CREATE TABLE sh_cart_items(item_id INTEGER PRIMARY KEY AUTOINCREMENT, cart_id TEXT,
            product_id TEXT, option_id TEXT, qty INTEGER);
    """)
    with open(os.path.join(BASE, "seed", "products.csv"), encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            con.execute("INSERT INTO sh_products VALUES(?,?,?,?,?,?,?)",
                        (r["product_id"].strip(), r["name"], to_int(r["price"]), to_int(r["sale_price"]),
                         to_int(r["stock"]), to_int(r["max_per_order"]), i))
    with open(os.path.join(BASE, "seed", "options.csv"), encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            con.execute("INSERT INTO sh_options VALUES(?,?,?,?,?)",
                        (r["option_id"].strip(), r["product_id"].strip(), r["label"], to_int(r["extra"]) or 0, i))
    con.commit()
    con.close()


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


async def body_of(request: Request):
    try:
        b = await request.json()
    except Exception:
        b = None
    return b if isinstance(b, dict) else {}


def valid_qty(v, minimum):
    return isinstance(v, int) and not isinstance(v, bool) and v >= minimum


def options_of(con, pid):
    return con.execute("SELECT * FROM sh_options WHERE product_id=? ORDER BY seq", (pid,)).fetchall()


def cart_view(con, cid):
    items, subtotal = [], 0
    rows = con.execute(
        """SELECT i.item_id, i.product_id, i.option_id, i.qty, p.name, p.price, p.sale_price,
                  o.label, o.extra
           FROM sh_cart_items i JOIN sh_products p ON p.product_id=i.product_id
           LEFT JOIN sh_options o ON o.option_id=i.option_id
           WHERE i.cart_id=? ORDER BY i.item_id""", (cid,)).fetchall()
    for r in rows:
        base = r["sale_price"] if r["sale_price"] is not None else r["price"]
        unit = base + (r["extra"] or 0)
        line = unit * r["qty"]
        subtotal += line
        items.append({"item_id": str(r["item_id"]), "product_id": r["product_id"], "option_id": r["option_id"],
                      "name": r["name"], "label": r["label"], "unit_price": unit, "qty": r["qty"],
                      "line_total": line})
    shipping = 0 if (not items or subtotal >= FREE_FROM) else SHIPPING
    return {"cart_id": cid, "items": items, "subtotal": subtotal, "shipping": shipping,
            "total": subtotal + shipping}


def check_limit(p, total_qty):
    lim = min(p["stock"], p["max_per_order"])
    if total_qty > lim:
        raise Reject(409, "최대 %d개까지 담을 수 있습니다" % lim)


def require_cart(con, cid):
    if not con.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cid,)).fetchone():
        raise Reject(404, "장바구니를 찾을 수 없습니다")


@app.get("/api/products")
def products():
    con = connect()
    out = []
    for p in con.execute("SELECT * FROM sh_products ORDER BY seq"):
        out.append({"product_id": p["product_id"], "name": p["name"], "price": p["price"],
                    "sale_price": p["sale_price"], "stock": p["stock"], "max_per_order": p["max_per_order"],
                    "sold_out": p["stock"] <= 0,
                    "options": [{"option_id": o["option_id"], "label": o["label"], "extra": o["extra"]}
                                for o in options_of(con, p["product_id"])]})
    con.close()
    return out


@app.post("/api/carts", status_code=201)
def create_cart():
    cid = uuid.uuid4().hex
    con = connect()
    con.execute("INSERT INTO sh_carts VALUES(?)", (cid,))
    con.commit()
    con.close()
    return {"cart_id": cid}


@app.get("/api/carts/{cart_id}")
def get_cart(cart_id: str):
    con = connect()
    try:
        require_cart(con, cart_id)
        return cart_view(con, cart_id)
    finally:
        con.close()


@app.post("/api/carts/{cart_id}/items", status_code=201)
async def add_item(cart_id: str, request: Request):
    b = await body_of(request)
    qty = b.get("qty")
    pid, oid = b.get("product_id"), b.get("option_id")
    if not valid_qty(qty, 1):
        raise Reject(400, "수량을 확인하세요")
    if not isinstance(pid, str) or (oid is not None and not isinstance(oid, str)):
        raise Reject(400, "상품을 확인하세요")
    con = connect()
    try:
        require_cart(con, cart_id)
        p = con.execute("SELECT * FROM sh_products WHERE product_id=?", (pid,)).fetchone()
        if not p:
            raise Reject(404, "상품을 찾을 수 없습니다")
        opts = options_of(con, pid)
        if opts:
            if oid is None or oid not in [o["option_id"] for o in opts]:
                raise Reject(400, "옵션을 확인하세요")
        elif oid is not None:
            raise Reject(400, "옵션을 확인하세요")
        if p["stock"] <= 0:
            raise Reject(409, "품절된 상품입니다")
        have = con.execute("SELECT COALESCE(SUM(qty),0) FROM sh_cart_items WHERE cart_id=? AND product_id=?",
                           (cart_id, pid)).fetchone()[0]
        check_limit(p, have + qty)
        row = con.execute("SELECT item_id FROM sh_cart_items WHERE cart_id=? AND product_id=? AND option_id IS ?",
                          (cart_id, pid, oid)).fetchone()
        if row:
            con.execute("UPDATE sh_cart_items SET qty=qty+? WHERE item_id=?", (qty, row["item_id"]))
        else:
            con.execute("INSERT INTO sh_cart_items(cart_id,product_id,option_id,qty) VALUES(?,?,?,?)",
                        (cart_id, pid, oid, qty))
        con.commit()
        return cart_view(con, cart_id)
    finally:
        con.close()


@app.put("/api/carts/{cart_id}/items/{item_id}")
async def update_item(cart_id: str, item_id: str, request: Request):
    b = await body_of(request)
    qty = b.get("qty")
    if not valid_qty(qty, 0):
        raise Reject(400, "수량을 확인하세요")
    con = connect()
    try:
        require_cart(con, cart_id)
        it = None
        if item_id.isdigit():
            it = con.execute("SELECT * FROM sh_cart_items WHERE item_id=? AND cart_id=?",
                             (int(item_id), cart_id)).fetchone()
        if not it:
            raise Reject(404, "장바구니 항목을 찾을 수 없습니다")
        if qty == 0:
            con.execute("DELETE FROM sh_cart_items WHERE item_id=?", (it["item_id"],))
        else:
            p = con.execute("SELECT * FROM sh_products WHERE product_id=?", (it["product_id"],)).fetchone()
            others = con.execute("""SELECT COALESCE(SUM(qty),0) FROM sh_cart_items
                                    WHERE cart_id=? AND product_id=? AND item_id<>?""",
                                 (cart_id, it["product_id"], it["item_id"])).fetchone()[0]
            check_limit(p, others + qty)
            con.execute("UPDATE sh_cart_items SET qty=? WHERE item_id=?", (qty, it["item_id"]))
        con.commit()
        return cart_view(con, cart_id)
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
