import csv
import os
import sqlite3
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "shop.db"
FREE_SHIPPING_FROM = 30000
SHIPPING_FEE = 3000

app = FastAPI()
_lock = threading.RLock()
_conn = None


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def read_csv(name):
    with open(SEED / name, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def init_db():
    global _conn
    if _conn is not None:
        _conn.close()
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(str(DB_PATH) + suffix)
        except FileNotFoundError:
            pass
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sh_products(
            product_id TEXT PRIMARY KEY, name TEXT NOT NULL, price INTEGER NOT NULL,
            sale_price INTEGER, stock INTEGER NOT NULL, max_per_order INTEGER NOT NULL,
            seq INTEGER NOT NULL);
        CREATE TABLE sh_options(
            option_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, label TEXT NOT NULL,
            extra INTEGER NOT NULL, seq INTEGER NOT NULL);
        CREATE TABLE sh_carts(cart_id TEXT PRIMARY KEY);
        CREATE TABLE sh_cart_items(
            item_id INTEGER PRIMARY KEY AUTOINCREMENT, cart_id TEXT NOT NULL,
            product_id TEXT NOT NULL, option_id TEXT, qty INTEGER NOT NULL);
        """
    )
    for i, r in enumerate(read_csv("products.csv")):
        sale = (r.get("sale_price") or "").strip()
        conn.execute(
            "INSERT INTO sh_products VALUES(?,?,?,?,?,?,?)",
            (r["product_id"].strip(), r["name"].strip(), int(r["price"]),
             int(sale) if sale else None, int(r["stock"]), int(r["max_per_order"]), i),
        )
    for i, r in enumerate(read_csv("options.csv")):
        conn.execute(
            "INSERT INTO sh_options VALUES(?,?,?,?,?)",
            (r["option_id"].strip(), r["product_id"].strip(), r["label"].strip(), int(r["extra"]), i),
        )
    conn.commit()
    _conn = conn


init_db()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


async def body_of(request):
    try:
        data = await request.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def cart_view(cart_id):
    rows = _conn.execute(
        """SELECT i.item_id, i.product_id, i.option_id, i.qty, p.name, p.price, p.sale_price,
                  o.label, o.extra
           FROM sh_cart_items i
           JOIN sh_products p ON p.product_id = i.product_id
           LEFT JOIN sh_options o ON o.option_id = i.option_id
           WHERE i.cart_id = ? ORDER BY i.item_id""",
        (cart_id,),
    ).fetchall()
    items = []
    subtotal = 0
    for r in rows:
        base = r["sale_price"] if r["sale_price"] is not None else r["price"]
        unit = base + (r["extra"] or 0)
        line = unit * r["qty"]
        subtotal += line
        items.append({
            "item_id": r["item_id"], "product_id": r["product_id"], "option_id": r["option_id"],
            "name": r["name"], "label": r["label"], "unit_price": unit,
            "qty": r["qty"], "line_total": line,
        })
    shipping = 0 if (not items or subtotal >= FREE_SHIPPING_FROM) else SHIPPING_FEE
    return {"cart_id": cart_id, "items": items, "subtotal": subtotal,
            "shipping": shipping, "total": subtotal + shipping}


def require_cart(cart_id):
    if _conn.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone() is None:
        raise Reject(404, "장바구니를 찾을 수 없습니다")


def check_limit(product, new_total):
    limit = min(product["stock"], product["max_per_order"])
    if new_total > limit:
        raise Reject(409, f"최대 {limit}개까지 담을 수 있습니다")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/products")
def products():
    with _lock:
        opts = {}
        for o in _conn.execute("SELECT * FROM sh_options ORDER BY seq"):
            opts.setdefault(o["product_id"], []).append(
                {"option_id": o["option_id"], "label": o["label"], "extra": o["extra"]})
        return [
            {"product_id": p["product_id"], "name": p["name"], "price": p["price"],
             "sale_price": p["sale_price"], "stock": p["stock"],
             "max_per_order": p["max_per_order"], "sold_out": p["stock"] <= 0,
             "options": opts.get(p["product_id"], [])}
            for p in _conn.execute("SELECT * FROM sh_products ORDER BY seq")
        ]


@app.post("/api/carts", status_code=201)
def create_cart():
    with _lock:
        cart_id = uuid.uuid4().hex
        _conn.execute("INSERT INTO sh_carts VALUES(?)", (cart_id,))
        _conn.commit()
        return {"cart_id": cart_id}


@app.get("/api/carts/{cart_id}")
def get_cart(cart_id: str):
    with _lock:
        require_cart(cart_id)
        return cart_view(cart_id)


@app.post("/api/carts/{cart_id}/items", status_code=201)
async def add_item(cart_id: str, request: Request):
    data = await body_of(request)
    with _lock:
        # R7: 400 -> 404 -> 409
        if data is None or not is_int(data.get("qty")) or data["qty"] < 1:
            raise Reject(400, "수량을 확인하세요")
        pid = data.get("product_id")
        oid = data.get("option_id")
        if not isinstance(pid, str) or (oid is not None and not isinstance(oid, str)):
            raise Reject(400, "옵션을 확인하세요")
        require_cart(cart_id)
        product = _conn.execute("SELECT * FROM sh_products WHERE product_id=?", (pid,)).fetchone()
        if product is None:
            raise Reject(404, "상품을 찾을 수 없습니다")
        valid = [o["option_id"] for o in
                 _conn.execute("SELECT option_id FROM sh_options WHERE product_id=?", (pid,))]
        if valid:
            if oid not in valid:
                raise Reject(400, "옵션을 확인하세요")
        elif oid is not None:
            raise Reject(400, "옵션을 확인하세요")
        if product["stock"] <= 0:
            raise Reject(409, "품절된 상품입니다")
        have = _conn.execute(
            "SELECT COALESCE(SUM(qty),0) FROM sh_cart_items WHERE cart_id=? AND product_id=?",
            (cart_id, pid)).fetchone()[0]
        check_limit(product, have + data["qty"])
        same = _conn.execute(
            "SELECT item_id FROM sh_cart_items WHERE cart_id=? AND product_id=? AND option_id IS ?",
            (cart_id, pid, oid)).fetchone()
        if same:
            _conn.execute("UPDATE sh_cart_items SET qty = qty + ? WHERE item_id=?",
                          (data["qty"], same["item_id"]))
        else:
            _conn.execute(
                "INSERT INTO sh_cart_items(cart_id, product_id, option_id, qty) VALUES(?,?,?,?)",
                (cart_id, pid, oid, data["qty"]))
        _conn.commit()
        return cart_view(cart_id)


@app.put("/api/carts/{cart_id}/items/{item_id}")
async def update_item(cart_id: str, item_id: str, request: Request):
    data = await body_of(request)
    with _lock:
        if data is None or not is_int(data.get("qty")) or data["qty"] < 0:
            raise Reject(400, "수량을 확인하세요")
        require_cart(cart_id)
        item = None
        if item_id.isdigit():
            item = _conn.execute("SELECT * FROM sh_cart_items WHERE item_id=? AND cart_id=?",
                                 (int(item_id), cart_id)).fetchone()
        if item is None:
            raise Reject(404, "장바구니 항목을 찾을 수 없습니다")
        qty = data["qty"]
        if qty == 0:
            _conn.execute("DELETE FROM sh_cart_items WHERE item_id=?", (item["item_id"],))
        else:
            product = _conn.execute("SELECT * FROM sh_products WHERE product_id=?",
                                    (item["product_id"],)).fetchone()
            others = _conn.execute(
                "SELECT COALESCE(SUM(qty),0) FROM sh_cart_items "
                "WHERE cart_id=? AND product_id=? AND item_id<>?",
                (cart_id, item["product_id"], item["item_id"])).fetchone()[0]
            check_limit(product, others + qty)
            _conn.execute("UPDATE sh_cart_items SET qty=? WHERE item_id=?", (qty, item["item_id"]))
        _conn.commit()
        return cart_view(cart_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
