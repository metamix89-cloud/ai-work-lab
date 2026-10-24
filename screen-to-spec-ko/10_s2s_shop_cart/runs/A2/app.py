"""가나다식품 소호 쇼핑몰 - FastAPI + SQLite (결제 없음)"""
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "shop.db"

FREE_SHIPPING_THRESHOLD = 50000
SHIPPING_FEE = 3000
MAX_QTY = 20

app = FastAPI(title="가나다식품 소호 쇼핑몰")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  emoji TEXT NOT NULL, description TEXT NOT NULL,
  price INTEGER NOT NULL,            -- 정가(원)
  discount_percent INTEGER NOT NULL DEFAULT 0,
  sold_out INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS options (
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  label TEXT NOT NULL, extra_price INTEGER NOT NULL DEFAULT 0,
  stock INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cart_items (
  id INTEGER PRIMARY KEY, cart_id TEXT NOT NULL,
  option_id INTEGER NOT NULL REFERENCES options(id), qty INTEGER NOT NULL,
  UNIQUE(cart_id, option_id)
);
"""

# (이름, 분류, 이모지, 설명, 정가, 할인%, 품절, [(옵션, 추가금, 재고)])
SEED = [
    ("국산 참기름", "양념/오일", "🫒", "국산 통참깨를 저온 압착한 고소한 참기름.", 15000, 0, 0,
     [("160ml", 0, 50), ("320ml", 11000, 30), ("선물세트 2병", 17000, 8)]),
    ("전통 간장", "양념/오일", "🍶", "3년 숙성 조선간장. 국, 나물, 무침용.", 9800, 20, 0,
     [("500ml", 0, 40), ("1L", 7000, 25)]),
    ("우리밀 약과", "간식", "🍪", "쫀득하고 달콤한 수제 약과.", 12000, 0, 0,
     [("10입", 0, 35), ("20입", 10000, 20)]),
    ("국산 대추칩", "간식", "🍂", "바삭하게 말린 경북 대추 칩.", 8500, 30, 0,
     [("50g", 0, 60), ("100g", 6000, 0), ("3팩 묶음", 14000, 12)]),
    ("수제 고추장", "양념/오일", "🌶️", "태양초 고춧가루로 담근 고추장.", 13500, 0, 1,
     [("500g", 0, 0), ("1kg", 10000, 0)]),
    ("현미 누룽지", "곡물", "🍚", "가마솥 방식으로 구운 현미 누룽지.", 7500, 10, 0,
     [("300g", 0, 80), ("600g", 6000, 40)]),
    ("제주 감귤청", "음료/청", "🍊", "제주 노지 감귤로 만든 청. 차로 드세요.", 16000, 25, 0,
     [("250g", 0, 20), ("500g", 11000, 10), ("1kg", 24000, 5)]),
    ("들기름 (냉동 생들기름)", "양념/오일", "🌿", "냉동 보관 생들기름, 신선한 향.", 18000, 0, 0,
     [("100ml", 0, 25), ("200ml", 14000, 15)]),
    ("보리차 티백", "음료/청", "🍵", "국산 볶음 보리 100% 티백.", 6000, 0, 0,
     [("30개입", 0, 100), ("60개입", 5000, 50)]),
    ("한우 육포", "간식", "🥩", "수제 한우 육포. 한정 수량.", 22000, 15, 1,
     [("80g", 0, 0)]),
]


def init_db():
    with closing(db()) as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            for name, cat, emoji, desc, price, disc, so, opts in SEED:
                cur = con.execute(
                    "INSERT INTO products(name,category,emoji,description,price,discount_percent,sold_out)"
                    " VALUES(?,?,?,?,?,?,?)", (name, cat, emoji, desc, price, disc, so))
                for label, extra, stock in opts:
                    con.execute("INSERT INTO options(product_id,label,extra_price,stock) VALUES(?,?,?,?)",
                                (cur.lastrowid, label, extra, stock))
        con.commit()


init_db()


def unit_price(price, extra, disc):
    """할인은 (정가+옵션추가금)에 적용, 10원 단위 반올림."""
    return round((price + extra) * (100 - disc) / 100 / 10) * 10


@app.get("/api/products")
def products():
    with closing(db()) as con:
        out = []
        for p in con.execute("SELECT * FROM products ORDER BY id"):
            opts = []
            for o in con.execute("SELECT * FROM options WHERE product_id=? ORDER BY id", (p["id"],)):
                opts.append({
                    "id": o["id"], "label": o["label"], "stock": o["stock"],
                    "sold_out": bool(p["sold_out"]) or o["stock"] <= 0,
                    "original_price": p["price"] + o["extra_price"],
                    "price": unit_price(p["price"], o["extra_price"], p["discount_percent"]),
                })
            out.append({
                "id": p["id"], "name": p["name"], "category": p["category"], "emoji": p["emoji"],
                "description": p["description"], "discount_percent": p["discount_percent"],
                "sold_out": all(o["sold_out"] for o in opts), "options": opts,
            })
        return out


def cart_view(con, cart_id):
    rows = con.execute(
        """SELECT c.id, c.qty, o.id AS option_id, o.label, o.extra_price, o.stock,
                  p.id AS product_id, p.name, p.emoji, p.price, p.discount_percent, p.sold_out
           FROM cart_items c JOIN options o ON o.id=c.option_id JOIN products p ON p.id=o.product_id
           WHERE c.cart_id=? ORDER BY c.id""", (cart_id,)).fetchall()
    items, subtotal, original = [], 0, 0
    for r in rows:
        unit = unit_price(r["price"], r["extra_price"], r["discount_percent"])
        orig = r["price"] + r["extra_price"]
        unavailable = bool(r["sold_out"]) or r["stock"] <= 0
        over = (not unavailable) and r["qty"] > r["stock"]
        line = unit * r["qty"]
        if not unavailable:  # 구매 불가 품목은 합계에서 제외
            subtotal += line
            original += orig * r["qty"]
        items.append({
            "id": r["id"], "product_id": r["product_id"], "name": r["name"], "emoji": r["emoji"],
            "option": r["label"], "qty": r["qty"], "stock": r["stock"], "unit_price": unit,
            "original_price": orig, "line_total": line, "unavailable": unavailable,
            "over_stock": over,
        })
    shipping = 0 if (subtotal == 0 or subtotal >= FREE_SHIPPING_THRESHOLD) else SHIPPING_FEE
    return {
        "items": items, "subtotal": subtotal, "discount_total": original - subtotal,
        "shipping": shipping, "total": subtotal + shipping,
        "free_shipping_threshold": FREE_SHIPPING_THRESHOLD,
        "remaining_for_free": max(0, FREE_SHIPPING_THRESHOLD - subtotal) if subtotal else FREE_SHIPPING_THRESHOLD,
    }


class AddItem(BaseModel):
    option_id: int
    qty: int = Field(ge=1, le=MAX_QTY)


class SetQty(BaseModel):
    qty: int = Field(ge=1, le=MAX_QTY)


@app.get("/api/cart/{cart_id}")
def get_cart(cart_id: str):
    with closing(db()) as con:
        return cart_view(con, cart_id)


@app.post("/api/cart/{cart_id}/items")
def add_item(cart_id: str, body: AddItem):
    with closing(db()) as con:
        o = con.execute("SELECT o.stock, p.sold_out FROM options o JOIN products p ON p.id=o.product_id"
                        " WHERE o.id=?", (body.option_id,)).fetchone()
        if not o:
            raise HTTPException(404, "존재하지 않는 옵션입니다.")
        if o["sold_out"] or o["stock"] <= 0:
            raise HTTPException(409, "품절된 상품입니다.")
        cur = con.execute("SELECT qty FROM cart_items WHERE cart_id=? AND option_id=?",
                          (cart_id, body.option_id)).fetchone()
        new_qty = (cur["qty"] if cur else 0) + body.qty
        if new_qty > min(o["stock"], MAX_QTY):
            raise HTTPException(409, f"최대 {min(o['stock'], MAX_QTY)}개까지 담을 수 있습니다.")
        con.execute("INSERT INTO cart_items(cart_id,option_id,qty) VALUES(?,?,?)"
                    " ON CONFLICT(cart_id,option_id) DO UPDATE SET qty=excluded.qty",
                    (cart_id, body.option_id, new_qty))
        con.commit()
        return cart_view(con, cart_id)


@app.patch("/api/cart/{cart_id}/items/{item_id}")
def set_qty(cart_id: str, item_id: int, body: SetQty):
    with closing(db()) as con:
        r = con.execute("SELECT o.stock, p.sold_out FROM cart_items c JOIN options o ON o.id=c.option_id"
                        " JOIN products p ON p.id=o.product_id WHERE c.id=? AND c.cart_id=?",
                        (item_id, cart_id)).fetchone()
        if not r:
            raise HTTPException(404, "장바구니 항목이 없습니다.")
        if r["sold_out"] or r["stock"] <= 0:
            raise HTTPException(409, "품절된 상품입니다. 삭제해 주세요.")
        if body.qty > min(r["stock"], MAX_QTY):
            raise HTTPException(409, f"최대 {min(r['stock'], MAX_QTY)}개까지 담을 수 있습니다.")
        con.execute("UPDATE cart_items SET qty=? WHERE id=?", (body.qty, item_id))
        con.commit()
        return cart_view(con, cart_id)


@app.delete("/api/cart/{cart_id}/items/{item_id}")
def remove_item(cart_id: str, item_id: int):
    with closing(db()) as con:
        con.execute("DELETE FROM cart_items WHERE id=? AND cart_id=?", (item_id, cart_id))
        con.commit()
        return cart_view(con, cart_id)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
