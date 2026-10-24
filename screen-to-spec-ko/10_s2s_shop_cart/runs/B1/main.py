import csv
import sqlite3
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "shop.db"
FREE_SHIPPING_FROM = 30000
SHIPPING_FEE = 3000


def init_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE sh_products(product_id TEXT PRIMARY KEY, name TEXT, price INTEGER,
            sale_price INTEGER, stock INTEGER, max_per_order INTEGER, ord INTEGER);
        CREATE TABLE sh_options(option_id TEXT PRIMARY KEY, product_id TEXT, label TEXT,
            extra INTEGER, ord INTEGER);
        CREATE TABLE sh_carts(cart_id TEXT PRIMARY KEY);
        CREATE TABLE sh_cart_items(item_id INTEGER PRIMARY KEY AUTOINCREMENT, cart_id TEXT,
            product_id TEXT, option_id TEXT, qty INTEGER);
        """
    )
    with open(BASE / "seed" / "products.csv", encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            sale = (r["sale_price"] or "").strip()
            con.execute(
                "INSERT INTO sh_products VALUES(?,?,?,?,?,?,?)",
                (r["product_id"].strip(), r["name"], int(r["price"]),
                 int(sale) if sale else None, int(r["stock"]), int(r["max_per_order"]), i),
            )
    with open(BASE / "seed" / "options.csv", encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f)):
            con.execute(
                "INSERT INTO sh_options VALUES(?,?,?,?,?)",
                (r["option_id"].strip(), r["product_id"].strip(), r["label"], int(r["extra"]), i),
            )
    con.commit()
    con.close()


init_db()
app = FastAPI()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


async def body_of(request: Request):
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def cart_view(con, cart_id):
    rows = con.execute(
        """SELECT i.item_id, i.product_id, i.option_id, i.qty, p.name, p.price, p.sale_price,
                  o.label, o.extra
           FROM sh_cart_items i JOIN sh_products p ON p.product_id = i.product_id
           LEFT JOIN sh_options o ON o.option_id = i.option_id
           WHERE i.cart_id = ? ORDER BY i.item_id""",
        (cart_id,),
    ).fetchall()
    items, subtotal = [], 0
    for r in rows:
        base = r["sale_price"] if r["sale_price"] is not None else r["price"]
        unit = base + (r["extra"] or 0)
        line = unit * r["qty"]
        subtotal += line
        items.append({"item_id": r["item_id"], "product_id": r["product_id"],
                      "option_id": r["option_id"], "name": r["name"], "label": r["label"],
                      "unit_price": unit, "qty": r["qty"], "line_total": line})
    shipping = 0 if (not items or subtotal >= FREE_SHIPPING_FROM) else SHIPPING_FEE
    return {"cart_id": cart_id, "items": items, "subtotal": subtotal,
            "shipping": shipping, "total": subtotal + shipping}


def cart_exists(con, cart_id):
    return con.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone() is not None


def limit_of(p):
    return min(p["stock"], p["max_per_order"])


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/products")
def products():
    con = db()
    opts = {}
    for o in con.execute("SELECT * FROM sh_options ORDER BY ord"):
        opts.setdefault(o["product_id"], []).append(
            {"option_id": o["option_id"], "label": o["label"], "extra": o["extra"]})
    out = [{"product_id": p["product_id"], "name": p["name"], "price": p["price"],
            "sale_price": p["sale_price"], "stock": p["stock"],
            "max_per_order": p["max_per_order"], "sold_out": p["stock"] <= 0,
            "options": opts.get(p["product_id"], [])}
           for p in con.execute("SELECT * FROM sh_products ORDER BY ord")]
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
        if not cart_exists(con, cart_id):
            raise Reject(404, "장바구니를 찾을 수 없습니다")
        return cart_view(con, cart_id)
    finally:
        con.close()


@app.post("/api/carts/{cart_id}/items", status_code=201)
async def add_item(cart_id: str, request: Request):
    b = await body_of(request)
    con = db()
    try:
        qty, pid, oid = b.get("qty"), b.get("product_id"), b.get("option_id")
        # 400: 입력 오류
        if not is_int(qty) or qty < 1:
            raise Reject(400, "수량을 확인하세요")
        if oid is not None and not isinstance(oid, str):
            raise Reject(400, "옵션을 확인하세요")
        # 404: 없는 장바구니 · 상품
        if not cart_exists(con, cart_id):
            raise Reject(404, "장바구니를 찾을 수 없습니다")
        p = con.execute("SELECT * FROM sh_products WHERE product_id=?", (pid,)).fetchone() \
            if isinstance(pid, str) else None
        if p is None:
            raise Reject(404, "상품을 찾을 수 없습니다")
        # 400: 옵션 (R7: 옵션 아님은 400)
        has_opts = con.execute("SELECT COUNT(*) FROM sh_options WHERE product_id=?", (pid,)).fetchone()[0] > 0
        if has_opts:
            ok = oid is not None and con.execute(
                "SELECT 1 FROM sh_options WHERE option_id=? AND product_id=?", (oid, pid)).fetchone()
            if not ok:
                raise Reject(400, "옵션을 확인하세요")
        elif oid is not None:
            raise Reject(400, "옵션을 확인하세요")
        # 409: 품절 · 한도
        if p["stock"] <= 0:
            raise Reject(409, "품절된 상품입니다")
        limit = limit_of(p)
        have = con.execute("SELECT COALESCE(SUM(qty),0) FROM sh_cart_items WHERE cart_id=? AND product_id=?",
                           (cart_id, pid)).fetchone()[0]
        if have + qty > limit:
            raise Reject(409, f"최대 {limit}개까지 담을 수 있습니다")
        row = con.execute(
            "SELECT item_id FROM sh_cart_items WHERE cart_id=? AND product_id=? AND option_id IS ?",
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
    con = db()
    try:
        qty = b.get("qty")
        if not is_int(qty) or qty < 0:
            raise Reject(400, "수량을 확인하세요")
        if not cart_exists(con, cart_id):
            raise Reject(404, "장바구니를 찾을 수 없습니다")
        item = con.execute("SELECT * FROM sh_cart_items WHERE cart_id=? AND item_id=?",
                           (cart_id, int(item_id))).fetchone() if item_id.isdigit() else None
        if item is None:
            raise Reject(404, "장바구니 항목을 찾을 수 없습니다")
        if qty == 0:
            con.execute("DELETE FROM sh_cart_items WHERE item_id=?", (item["item_id"],))
        else:
            p = con.execute("SELECT * FROM sh_products WHERE product_id=?", (item["product_id"],)).fetchone()
            others = con.execute(
                "SELECT COALESCE(SUM(qty),0) FROM sh_cart_items WHERE cart_id=? AND product_id=? AND item_id<>?",
                (cart_id, item["product_id"], item["item_id"])).fetchone()[0]
            limit = limit_of(p)
            if others + qty > limit:
                raise Reject(409, f"최대 {limit}개까지 담을 수 있습니다")
            con.execute("UPDATE sh_cart_items SET qty=? WHERE item_id=?", (qty, item["item_id"]))
        con.commit()
        return cart_view(con, cart_id)
    finally:
        con.close()
