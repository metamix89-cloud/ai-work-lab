import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "shop.db"
FREE_SHIPPING_MIN = 30000
SHIPPING_FEE = 3000
MAX_QTY = 99

# (name, category, price, discount_pct, emoji, description, [(option, extra_price, stock)])
SEED = [
    ("가나다 포기김치", "김치", 15900, 0, "🥬", "국내산 배추로 담근 아삭한 포기김치.",
     [("1kg", 0, 40), ("3kg", 22000, 15)]),
    ("국산 볶음김치", "김치", 8900, 20, "🌶️", "푹 익은 김치를 볶아낸 밥도둑.",
     [("300g", 0, 25), ("300g x 3팩", 15000, 8)]),
    ("수제 만두 800g", "간편식", 9800, 0, "🥟", "얇은 피에 속을 가득 채운 수제 만두.",
     [("고기만두", 0, 30), ("김치만두", 0, 0), ("반반", 500, 12)]),
    ("한우 사골곰탕 500ml", "간편식", 6500, 30, "🍲", "12시간 우려낸 진한 국물. 데우기만 하면 끝.",
     [("1팩", 0, 50), ("5팩", 24000, 20)]),
    ("국산 참기름 320ml", "양념", 18000, 10, "🫙", "저온 압착 방식으로 짠 고소한 참기름.",
     [("320ml", 0, 18)]),
    ("전통 고추장 1kg", "양념", 12500, 0, "🌶️", "태양초로 만든 구수한 고추장.",
     [("1kg", 0, 0)]),
    ("제주 감귤 2.5kg", "과일", 14900, 15, "🍊", "새콤달콤한 노지 감귤.",
     [("소과 (S)", 0, 22), ("중과 (M)", 2000, 14), ("대과 (L)", 4000, 0)]),
    ("수제 약과", "디저트", 7900, 0, "🍪", "쫀득하고 달콤한 전통 수제 약과.",
     [("10입", 0, 35), ("20입", 7000, 10)]),
    ("현미 누룽지 500g", "간식", 5900, 25, "🍚", "구수한 현미 누룽지, 끓여 먹거나 그대로 간식으로.",
     [("500g", 0, 60)]),
    ("들기름 막국수 세트", "간편식", 11900, 0, "🍜", "메밀면과 들기름 소스 포함.",
     [("2인분", 0, 16), ("4인분", 10000, 0)]),
]

app = FastAPI(title="가나다식품 소호 쇼핑몰")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    with closing(db()) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
            price INTEGER NOT NULL, discount_pct INTEGER NOT NULL DEFAULT 0,
            emoji TEXT, description TEXT);
        CREATE TABLE IF NOT EXISTS options(
            id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
            name TEXT NOT NULL, extra_price INTEGER NOT NULL DEFAULT 0, stock INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS cart_items(
            cart_id TEXT NOT NULL, option_id INTEGER NOT NULL REFERENCES options(id),
            qty INTEGER NOT NULL, PRIMARY KEY(cart_id, option_id));
        """)
        if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            for name, cat, price, pct, emoji, desc, opts in SEED:
                pid = con.execute(
                    "INSERT INTO products(name,category,price,discount_pct,emoji,description) VALUES(?,?,?,?,?,?)",
                    (name, cat, price, pct, emoji, desc)).lastrowid
                con.executemany(
                    "INSERT INTO options(product_id,name,extra_price,stock) VALUES(?,?,?,?)",
                    [(pid, o, e, s) for o, e, s in opts])
        con.commit()


def sale_price(price: int, pct: int) -> int:
    """할인가 (10원 단위 반올림)."""
    return round(price * (100 - pct) / 100 / 10) * 10


init_db()


@app.get("/api/products")
def products():
    with closing(db()) as con:
        out = []
        for p in con.execute("SELECT * FROM products ORDER BY id"):
            opts = con.execute("SELECT * FROM options WHERE product_id=? ORDER BY id", (p["id"],)).fetchall()
            options = [{
                "id": o["id"], "name": o["name"], "stock": o["stock"],
                "price": sale_price(p["price"] + o["extra_price"], p["discount_pct"]),
                "original_price": p["price"] + o["extra_price"],
            } for o in opts]
            out.append({
                "id": p["id"], "name": p["name"], "category": p["category"],
                "emoji": p["emoji"], "description": p["description"],
                "original_price": p["price"], "discount_pct": p["discount_pct"],
                "price": sale_price(p["price"], p["discount_pct"]),
                "sold_out": all(o["stock"] <= 0 for o in options),
                "options": options,
            })
        return out


def cart_view(con, cart_id: str):
    rows = con.execute("""
        SELECT ci.option_id, ci.qty, o.name AS option_name, o.extra_price, o.stock,
               p.id AS product_id, p.name, p.emoji, p.price, p.discount_pct
        FROM cart_items ci JOIN options o ON o.id = ci.option_id
        JOIN products p ON p.id = o.product_id
        WHERE ci.cart_id = ? ORDER BY ci.rowid""", (cart_id,)).fetchall()
    items, subtotal, discount = [], 0, 0
    for r in rows:
        orig = r["price"] + r["extra_price"]
        unit = sale_price(orig, r["discount_pct"])
        qty = r["qty"]
        ok = r["stock"] >= qty  # 품절이거나 재고가 담은 수량보다 적으면 합계에서 제외
        items.append({
            "option_id": r["option_id"], "product_id": r["product_id"], "name": r["name"],
            "emoji": r["emoji"], "option_name": r["option_name"], "qty": qty,
            "unit_price": unit, "original_price": orig, "stock": r["stock"],
            "line_total": unit * qty, "available": ok,
        })
        if ok:
            subtotal += unit * qty
            discount += (orig - unit) * qty
    shipping = 0 if (subtotal == 0 or subtotal >= FREE_SHIPPING_MIN) else SHIPPING_FEE
    return {
        "items": items, "subtotal": subtotal, "discount_total": discount,
        "shipping": shipping, "total": subtotal + shipping,
        "free_shipping_min": FREE_SHIPPING_MIN, "shipping_fee": SHIPPING_FEE,
        "remaining_for_free": max(0, FREE_SHIPPING_MIN - subtotal),
        "count": sum(i["qty"] for i in items),
    }


class AddItem(BaseModel):
    option_id: int
    qty: int = Field(1, ge=1, le=MAX_QTY)


class SetQty(BaseModel):
    qty: int = Field(ge=1, le=MAX_QTY)


def get_option(con, option_id):
    o = con.execute("SELECT * FROM options WHERE id=?", (option_id,)).fetchone()
    if not o:
        raise HTTPException(404, "존재하지 않는 옵션입니다.")
    return o


@app.get("/api/cart/{cart_id}")
def get_cart(cart_id: str):
    with closing(db()) as con:
        return cart_view(con, cart_id)


@app.post("/api/cart/{cart_id}/items")
def add_item(cart_id: str, body: AddItem):
    with closing(db()) as con:
        o = get_option(con, body.option_id)
        if o["stock"] <= 0:
            raise HTTPException(409, "품절된 상품입니다.")
        row = con.execute("SELECT qty FROM cart_items WHERE cart_id=? AND option_id=?",
                          (cart_id, body.option_id)).fetchone()
        new_qty = (row["qty"] if row else 0) + body.qty
        if new_qty > o["stock"]:
            raise HTTPException(409, f"재고가 부족합니다. (남은 수량 {o['stock']}개)")
        con.execute("""INSERT INTO cart_items(cart_id, option_id, qty) VALUES(?,?,?)
                       ON CONFLICT(cart_id, option_id) DO UPDATE SET qty=excluded.qty""",
                    (cart_id, body.option_id, new_qty))
        con.commit()
        return cart_view(con, cart_id)


@app.put("/api/cart/{cart_id}/items/{option_id}")
def set_qty(cart_id: str, option_id: int, body: SetQty):
    with closing(db()) as con:
        o = get_option(con, option_id)
        if body.qty > o["stock"]:
            raise HTTPException(409, f"재고가 부족합니다. (남은 수량 {o['stock']}개)")
        con.execute("UPDATE cart_items SET qty=? WHERE cart_id=? AND option_id=?",
                    (body.qty, cart_id, option_id))
        con.commit()
        return cart_view(con, cart_id)


@app.delete("/api/cart/{cart_id}/items/{option_id}")
def remove_item(cart_id: str, option_id: int):
    with closing(db()) as con:
        con.execute("DELETE FROM cart_items WHERE cart_id=? AND option_id=?", (cart_id, option_id))
        con.commit()
        return cart_view(con, cart_id)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
