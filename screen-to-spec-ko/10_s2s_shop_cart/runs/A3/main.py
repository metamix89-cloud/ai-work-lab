"""가나다식품 소호 쇼핑몰 - 상품 목록 + 장바구니 (FastAPI + SQLite)"""
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "shop.db"

FREE_SHIPPING_MIN = 30000  # 할인 적용 후 상품 합계가 이 금액 이상이면 무료배송
SHIPPING_FEE = 3000
MAX_QTY = 10

app = FastAPI(title="가나다식품 소호 쇼핑몰")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


SCHEMA = """
CREATE TABLE products (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  emoji TEXT NOT NULL, description TEXT NOT NULL,
  price INTEGER NOT NULL, discount_rate INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE options (
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
  name TEXT NOT NULL, extra_price INTEGER NOT NULL DEFAULT 0, stock INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE cart_items (
  cart_id TEXT NOT NULL, option_id INTEGER NOT NULL REFERENCES options(id),
  qty INTEGER NOT NULL, PRIMARY KEY (cart_id, option_id)
);
"""

# (이름, 분류, 이모지, 설명, 정가, 할인율, [(옵션명, 추가금, 재고)])
SEED = [
    ("국내산 김치 (포기김치)", "김치/반찬", "🥬", "국산 배추와 고춧가루로 담근 숙성 포기김치.", 18000, 0,
     [("1kg", 0, 40), ("3kg", 22000, 15), ("5kg", 40000, 0)]),
    ("수제 참기름", "양념/소스", "🫙", "저온 압착 국산 참깨 100% 참기름.", 15000, 20,
     [("160ml", 0, 30), ("320ml", 11000, 12)]),
    ("전통 고추장", "양념/소스", "🌶️", "3년 숙성 찹쌀 고추장.", 12000, 0,
     [("500g", 0, 25), ("1kg", 9000, 10)]),
    ("명란젓", "젓갈", "🐟", "저염 숙성 명란젓, 선물용으로 인기.", 28000, 15,
     [("200g", 0, 8), ("400g", 25000, 3)]),
    ("현미 누룽지", "간식", "🍘", "가마솥 방식으로 구운 고소한 누룽지.", 7500, 0,
     [("300g", 0, 100), ("600g", 6500, 60)]),
    ("한우 육포", "간식", "🥩", "국내산 한우 홍두깨살로 만든 육포.", 24000, 0,
     [("원조맛", 0, 0), ("매운맛", 0, 0)]),  # 전 옵션 품절 → 상품 품절
    ("제주 감귤 한과", "간식", "🍊", "제주 감귤 껍질을 넣은 유과 세트.", 16000, 30,
     [("소(10입)", 0, 20), ("대(20입)", 14000, 9)]),
    ("들기름", "양념/소스", "🫒", "국산 들깨 저온 압착 들기름.", 17000, 10,
     [("160ml", 0, 22), ("320ml", 13000, 0)]),
    ("깻잎 장아찌", "김치/반찬", "🍃", "간장에 숙성시킨 깻잎 장아찌.", 6500, 0,
     [("200g", 0, 50)]),
    ("수제 약과", "간식", "🍪", "꿀과 생강으로 반죽한 전통 약과.", 9800, 25,
     [("6개입", 0, 35), ("12개입", 8000, 18)]),
]


def init_db():
    if DB_PATH.exists():
        return
    with closing(db()) as con:
        con.executescript(SCHEMA)
        for name, cat, emoji, desc, price, rate, opts in SEED:
            cur = con.execute(
                "INSERT INTO products(name,category,emoji,description,price,discount_rate) VALUES (?,?,?,?,?,?)",
                (name, cat, emoji, desc, price, rate))
            for oname, extra, stock in opts:
                con.execute("INSERT INTO options(product_id,name,extra_price,stock) VALUES (?,?,?,?)",
                            (cur.lastrowid, oname, extra, stock))
        con.commit()


init_db()


def sale_price(price: int, extra: int, rate: int) -> int:
    """할인은 (기본가 + 옵션 추가금)에 적용, 10원 단위 반올림."""
    return round((price + extra) * (100 - rate) / 100 / 10) * 10


@app.get("/api/products")
def list_products():
    with closing(db()) as con:
        out = []
        for p in con.execute("SELECT * FROM products ORDER BY id"):
            opts = []
            for o in con.execute("SELECT * FROM options WHERE product_id=? ORDER BY id", (p["id"],)):
                opts.append({
                    "id": o["id"], "name": o["name"], "stock": o["stock"],
                    "original_price": p["price"] + o["extra_price"],
                    "price": sale_price(p["price"], o["extra_price"], p["discount_rate"]),
                })
            out.append({
                "id": p["id"], "name": p["name"], "category": p["category"], "emoji": p["emoji"],
                "description": p["description"], "discount_rate": p["discount_rate"],
                "sold_out": all(o["stock"] <= 0 for o in opts), "options": opts,
            })
        return out


class CartAdd(BaseModel):
    option_id: int
    qty: int = Field(ge=1, le=MAX_QTY)


class CartQty(BaseModel):
    qty: int = Field(ge=1, le=MAX_QTY)


def cart_view(con, cart_id: str):
    rows = con.execute("""
        SELECT c.option_id, c.qty, o.name AS option_name, o.extra_price, o.stock,
               p.id AS product_id, p.name, p.emoji, p.price, p.discount_rate
        FROM cart_items c JOIN options o ON o.id=c.option_id JOIN products p ON p.id=o.product_id
        WHERE c.cart_id=? ORDER BY c.rowid""", (cart_id,)).fetchall()
    items, subtotal, discount, count = [], 0, 0, 0
    for r in rows:
        unit = sale_price(r["price"], r["extra_price"], r["discount_rate"])
        orig = r["price"] + r["extra_price"]
        problem = None
        if r["stock"] <= 0:
            problem = "품절"
        elif r["qty"] > r["stock"]:
            problem = f"재고 부족 (남은 수량 {r['stock']}개)"
        items.append({
            "option_id": r["option_id"], "product_id": r["product_id"], "name": r["name"],
            "emoji": r["emoji"], "option_name": r["option_name"], "qty": r["qty"],
            "unit_price": unit, "original_unit_price": orig, "line_total": unit * r["qty"],
            "stock": r["stock"], "problem": problem,
        })
        if not problem:  # 구매 불가 항목은 합계에서 제외
            subtotal += unit * r["qty"]
            discount += (orig - unit) * r["qty"]
            count += r["qty"]
    shipping = 0 if (subtotal == 0 or subtotal >= FREE_SHIPPING_MIN) else SHIPPING_FEE
    return {
        "items": items, "count": count, "subtotal": subtotal, "discount": discount,
        "shipping": shipping, "total": subtotal + shipping,
        "free_shipping_min": FREE_SHIPPING_MIN,
        "remaining_for_free": max(0, FREE_SHIPPING_MIN - subtotal) if subtotal else FREE_SHIPPING_MIN,
        "has_problem": any(i["problem"] for i in items),
    }


@app.get("/api/cart/{cart_id}")
def get_cart(cart_id: str):
    with closing(db()) as con:
        return cart_view(con, cart_id)


@app.post("/api/cart/{cart_id}/items")
def add_item(cart_id: str, body: CartAdd):
    with closing(db()) as con:
        o = con.execute("SELECT stock FROM options WHERE id=?", (body.option_id,)).fetchone()
        if not o:
            raise HTTPException(404, "존재하지 않는 옵션입니다.")
        if o["stock"] <= 0:
            raise HTTPException(409, "품절된 상품입니다.")
        cur = con.execute("SELECT qty FROM cart_items WHERE cart_id=? AND option_id=?",
                          (cart_id, body.option_id)).fetchone()
        new_qty = (cur["qty"] if cur else 0) + body.qty
        if new_qty > min(o["stock"], MAX_QTY):
            raise HTTPException(409, f"담을 수 있는 최대 수량은 {min(o['stock'], MAX_QTY)}개입니다.")
        con.execute("""INSERT INTO cart_items(cart_id,option_id,qty) VALUES (?,?,?)
                       ON CONFLICT(cart_id,option_id) DO UPDATE SET qty=excluded.qty""",
                    (cart_id, body.option_id, new_qty))
        con.commit()
        return cart_view(con, cart_id)


@app.put("/api/cart/{cart_id}/items/{option_id}")
def set_qty(cart_id: str, option_id: int, body: CartQty):
    with closing(db()) as con:
        o = con.execute("SELECT stock FROM options WHERE id=?", (option_id,)).fetchone()
        if not o:
            raise HTTPException(404, "존재하지 않는 옵션입니다.")
        if body.qty > min(o["stock"], MAX_QTY):
            raise HTTPException(409, f"담을 수 있는 최대 수량은 {max(0, min(o['stock'], MAX_QTY))}개입니다.")
        if con.execute("UPDATE cart_items SET qty=? WHERE cart_id=? AND option_id=?",
                       (body.qty, cart_id, option_id)).rowcount == 0:
            raise HTTPException(404, "장바구니에 없는 상품입니다.")
        con.commit()
        return cart_view(con, cart_id)


@app.delete("/api/cart/{cart_id}/items/{option_id}")
def remove_item(cart_id: str, option_id: int):
    with closing(db()) as con:
        con.execute("DELETE FROM cart_items WHERE cart_id=? AND option_id=?", (cart_id, option_id))
        con.commit()
        return cart_view(con, cart_id)


@app.delete("/api/cart/{cart_id}")
def clear_cart(cart_id: str):
    with closing(db()) as con:
        con.execute("DELETE FROM cart_items WHERE cart_id=?", (cart_id,))
        con.commit()
        return cart_view(con, cart_id)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
