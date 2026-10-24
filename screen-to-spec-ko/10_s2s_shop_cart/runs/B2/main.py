import csv
import sqlite3
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "shop.db"
FREE_SHIPPING_FROM = 30000
SHIPPING_FEE = 3000

app = FastAPI()
_lock = threading.RLock()
_db = None


def init_db():
    """시작할 때마다 seed CSV 로 shop.db 를 새로 만든다."""
    global _db
    with _lock:
        if _db is not None:
            _db.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            p = Path(str(DB_PATH) + suffix)
            if p.exists():
                p.unlink()
        db = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.executescript(
            """
            CREATE TABLE sh_products(product_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                price INTEGER NOT NULL, sale_price INTEGER, stock INTEGER NOT NULL,
                max_per_order INTEGER NOT NULL, sort_no INTEGER NOT NULL);
            CREATE TABLE sh_options(option_id TEXT PRIMARY KEY, product_id TEXT NOT NULL,
                label TEXT NOT NULL, extra INTEGER NOT NULL, sort_no INTEGER NOT NULL);
            CREATE TABLE sh_carts(cart_id TEXT PRIMARY KEY);
            CREATE TABLE sh_cart_items(item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                cart_id TEXT NOT NULL, product_id TEXT NOT NULL, option_id TEXT, qty INTEGER NOT NULL);
            """
        )
        with open(BASE / "seed" / "products.csv", encoding="utf-8-sig", newline="") as f:
            for i, r in enumerate(csv.DictReader(f)):
                sale = (r["sale_price"] or "").strip()
                db.execute(
                    "INSERT INTO sh_products VALUES(?,?,?,?,?,?,?)",
                    (r["product_id"].strip(), r["name"].strip(), int(r["price"]),
                     int(sale) if sale else None, int(r["stock"]), int(r["max_per_order"]), i),
                )
        with open(BASE / "seed" / "options.csv", encoding="utf-8-sig", newline="") as f:
            for i, r in enumerate(csv.DictReader(f)):
                db.execute(
                    "INSERT INTO sh_options VALUES(?,?,?,?,?)",
                    (r["option_id"].strip(), r["product_id"].strip(), r["label"].strip(),
                     int(r["extra"]), i),
                )
        db.commit()
        _db = db


init_db()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def _reject(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


async def read_body(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def limit_of(p):
    return min(p["stock"], p["max_per_order"])


def cart_view(cart_id):
    rows = _db.execute(
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


def product_qty(cart_id, product_id, exclude_item=None):
    row = _db.execute(
        "SELECT COALESCE(SUM(qty),0) FROM sh_cart_items WHERE cart_id=? AND product_id=? AND item_id IS NOT ?",
        (cart_id, product_id, exclude_item),
    ).fetchone()
    return row[0]


def check_limit(p, total):
    if total > limit_of(p):
        raise Reject(409, f"최대 {limit_of(p)}개까지 담을 수 있습니다")


def require_cart(cart_id):
    if not _db.execute("SELECT 1 FROM sh_carts WHERE cart_id=?", (cart_id,)).fetchone():
        raise Reject(404, "장바구니를 찾을 수 없습니다")


@app.get("/api/products")
def products():
    with _lock:
        out = []
        for p in _db.execute("SELECT * FROM sh_products ORDER BY sort_no").fetchall():
            opts = _db.execute(
                "SELECT option_id,label,extra FROM sh_options WHERE product_id=? ORDER BY sort_no",
                (p["product_id"],),
            ).fetchall()
            out.append({"product_id": p["product_id"], "name": p["name"], "price": p["price"],
                        "sale_price": p["sale_price"], "stock": p["stock"],
                        "max_per_order": p["max_per_order"], "sold_out": p["stock"] <= 0,
                        "options": [dict(o) for o in opts]})
        return out


@app.post("/api/carts", status_code=201)
def create_cart():
    with _lock:
        cart_id = uuid.uuid4().hex
        _db.execute("INSERT INTO sh_carts VALUES(?)", (cart_id,))
        _db.commit()
        return {"cart_id": cart_id}


@app.get("/api/carts/{cart_id}")
def get_cart(cart_id: str):
    with _lock:
        require_cart(cart_id)
        return cart_view(cart_id)


@app.post("/api/carts/{cart_id}/items", status_code=201)
async def add_item(cart_id: str, request: Request):
    body = await read_body(request)
    product_id, option_id, qty = body.get("product_id"), body.get("option_id"), body.get("qty")
    # R7 1단계: 입력 오류 (400)
    if not is_int(qty) or qty < 1:
        raise Reject(400, "수량을 확인하세요")
    if not isinstance(product_id, str):
        raise Reject(400, "상품을 확인하세요")
    if option_id is not None and not isinstance(option_id, str):
        raise Reject(400, "옵션을 확인하세요")
    with _lock:
        p = _db.execute("SELECT * FROM sh_products WHERE product_id=?", (product_id,)).fetchone()
        if p:
            n_opts = _db.execute(
                "SELECT COUNT(*) FROM sh_options WHERE product_id=?", (product_id,)).fetchone()[0]
            if n_opts == 0:
                if option_id is not None:
                    raise Reject(400, "옵션을 확인하세요")
            else:
                ok = option_id is not None and _db.execute(
                    "SELECT 1 FROM sh_options WHERE option_id=? AND product_id=?",
                    (option_id, product_id)).fetchone()
                if not ok:
                    raise Reject(400, "옵션을 확인하세요")
        # R7 2단계: 없는 장바구니 · 상품 (404)
        require_cart(cart_id)
        if not p:
            raise Reject(404, "상품을 찾을 수 없습니다")
        # R7 3단계: 품절 · 한도 (409)
        if p["stock"] <= 0:
            raise Reject(409, "품절된 상품입니다")
        check_limit(p, product_qty(cart_id, product_id) + qty)
        row = _db.execute(
            "SELECT item_id FROM sh_cart_items WHERE cart_id=? AND product_id=? AND option_id IS ?",
            (cart_id, product_id, option_id),
        ).fetchone()
        if row:
            _db.execute("UPDATE sh_cart_items SET qty = qty + ? WHERE item_id=?", (qty, row["item_id"]))
        else:
            _db.execute("INSERT INTO sh_cart_items(cart_id,product_id,option_id,qty) VALUES(?,?,?,?)",
                        (cart_id, product_id, option_id, qty))
        _db.commit()
        return cart_view(cart_id)


@app.put("/api/carts/{cart_id}/items/{item_id}")
async def change_item(cart_id: str, item_id: str, request: Request):
    body = await read_body(request)
    qty = body.get("qty")
    if not is_int(qty) or qty < 0:
        raise Reject(400, "수량을 확인하세요")
    with _lock:
        require_cart(cart_id)
        item = None
        if item_id.isdigit():
            item = _db.execute("SELECT * FROM sh_cart_items WHERE item_id=? AND cart_id=?",
                               (int(item_id), cart_id)).fetchone()
        if not item:
            raise Reject(404, "장바구니 항목을 찾을 수 없습니다")
        if qty == 0:
            _db.execute("DELETE FROM sh_cart_items WHERE item_id=?", (item["item_id"],))
        else:
            p = _db.execute("SELECT * FROM sh_products WHERE product_id=?",
                            (item["product_id"],)).fetchone()
            check_limit(p, product_qty(cart_id, item["product_id"], item["item_id"]) + qty)
            _db.execute("UPDATE sh_cart_items SET qty=? WHERE item_id=?", (qty, item["item_id"]))
        _db.commit()
        return cart_view(cart_id)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html; charset=utf-8")
