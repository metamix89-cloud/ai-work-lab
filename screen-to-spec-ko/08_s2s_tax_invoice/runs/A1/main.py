import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "invoices.db"
TAX_RATE = 10  # 부가세율(%)

SUPPLIER = {
    "name": "가나다식품",
    "biz_no": "123-45-67890",
    "ceo": "김가나",
    "address": "서울특별시 송파구 올림픽로 300",
}

app = FastAPI(title="가나다식품 세금계산서")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    con = db()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            biz_no TEXT NOT NULL,
            ceo TEXT NOT NULL,
            address TEXT NOT NULL,
            email TEXT
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT NOT NULL UNIQUE,
            issue_date TEXT NOT NULL,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            supply_total INTEGER NOT NULL,
            tax_total INTEGER NOT NULL,
            grand_total INTEGER NOT NULL,
            memo TEXT DEFAULT '',
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            spec TEXT DEFAULT '',
            qty INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            taxable INTEGER NOT NULL DEFAULT 1,
            supply INTEGER NOT NULL,
            tax INTEGER NOT NULL
        );
        """
    )
    con.commit()
    if con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        seed(con)
    con.close()


PRODUCTS = [
    ("국산 쌀 20kg", "포대", 52000, 1),
    ("진간장 1.8L", "병", 6800, 1),
    ("태양초 고춧가루 1kg", "봉", 24000, 1),
    ("냉동 만두 1kg", "봉", 8500, 1),
    ("참기름 500ml", "병", 15000, 1),
    ("김치 5kg", "박스", 32000, 1),
    ("생두부 300g", "모", 1800, 0),   # 면세
    ("신선 계란 30구", "판", 7500, 0),  # 면세
    ("국내산 배추", "망", 9000, 0),    # 면세
]


def calc(items):
    """품목별 공급가/세액 계산. 과세 품목만 10% (원 단위 절사)."""
    rows, supply_total, tax_total = [], 0, 0
    for it in items:
        supply = it["qty"] * it["unit_price"]
        tax = supply * TAX_RATE // 100 if it["taxable"] else 0
        rows.append({**it, "supply": supply, "tax": tax})
        supply_total += supply
        tax_total += tax
    return rows, supply_total, tax_total


def next_invoice_no(con, issue_date):
    prefix = issue_date.replace("-", "")
    n = con.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(invoice_no, 10) AS INTEGER)), 0) FROM invoices WHERE invoice_no LIKE ?",
        (prefix + "-%",),
    ).fetchone()[0]
    return f"{prefix}-{n + 1:04d}"


def insert_invoice(con, issue_date, customer_id, memo, items):
    rows, s, t = calc(items)
    cur = con.execute(
        "INSERT INTO invoices(invoice_no, issue_date, customer_id, supply_total, tax_total, grand_total, memo)"
        " VALUES (?,?,?,?,?,?,?)",
        (next_invoice_no(con, issue_date), issue_date, customer_id, s, t, s + t, memo),
    )
    inv_id = cur.lastrowid
    con.executemany(
        "INSERT INTO invoice_items(invoice_id, name, spec, qty, unit_price, taxable, supply, tax)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(inv_id, r["name"], r["spec"], r["qty"], r["unit_price"], int(r["taxable"]), r["supply"], r["tax"]) for r in rows],
    )
    return inv_id


def seed(con):
    customers = [
        ("한울마트", "214-81-12345", "박한울", "서울특별시 강남구 테헤란로 101", "hanul@example.com"),
        ("푸른식당", "107-86-23456", "이푸른", "서울특별시 마포구 월드컵로 25", "green@example.com"),
        ("행복급식㈜", "312-81-34567", "최행복", "경기도 성남시 분당구 판교로 256", "happy@example.com"),
        ("바다횟집", "502-15-45678", "정바다", "부산광역시 해운대구 해운대로 570", "sea@example.com"),
        ("올데이카페", "220-88-56789", "강올데", "대전광역시 서구 둔산로 100", "allday@example.com"),
        ("미소푸드", "134-81-67890", "윤미소", "인천광역시 남동구 구월로 88", "miso@example.com"),
    ]
    con.executemany(
        "INSERT INTO customers(name, biz_no, ceo, address, email) VALUES (?,?,?,?,?)", customers
    )
    rnd = random.Random(7)
    today = date.today()
    for i in range(12):
        d = (today - timedelta(days=(11 - i) * 3)).isoformat()
        items = []
        for p in rnd.sample(PRODUCTS, rnd.randint(2, 4)):
            items.append(
                {"name": p[0], "spec": p[1], "qty": rnd.randint(1, 20), "unit_price": p[2], "taxable": p[3]}
            )
        insert_invoice(con, d, rnd.randint(1, len(customers)), "", items)
    con.commit()


class Item(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    spec: str = Field(default="", max_length=30)
    qty: int = Field(gt=0, le=1_000_000)
    unit_price: int = Field(ge=0, le=1_000_000_000)
    taxable: bool = True


class InvoiceIn(BaseModel):
    issue_date: date
    customer_id: int
    memo: str = Field(default="", max_length=200)
    items: list[Item] = Field(min_length=1, max_length=50)


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    biz_no: str = Field(pattern=r"^\d{3}-\d{2}-\d{5}$")
    ceo: str = Field(min_length=1, max_length=30)
    address: str = Field(min_length=1, max_length=200)
    email: str = ""


def load_invoice(con, inv_id):
    inv = con.execute(
        "SELECT i.*, c.name AS customer_name, c.biz_no AS customer_biz_no, c.ceo AS customer_ceo,"
        " c.address AS customer_address FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.id = ?",
        (inv_id,),
    ).fetchone()
    if not inv:
        raise HTTPException(404, "계산서를 찾을 수 없습니다.")
    items = con.execute("SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id", (inv_id,)).fetchall()
    return {**dict(inv), "items": [dict(r) for r in items], "supplier": SUPPLIER}


def check_customer(con, cid):
    if not con.execute("SELECT 1 FROM customers WHERE id = ?", (cid,)).fetchone():
        raise HTTPException(400, "존재하지 않는 거래처입니다.")


@app.get("/api/customers")
def list_customers():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM customers ORDER BY name")]


@app.post("/api/customers", status_code=201)
def add_customer(c: CustomerIn):
    with db() as con:
        cur = con.execute(
            "INSERT INTO customers(name, biz_no, ceo, address, email) VALUES (?,?,?,?,?)",
            (c.name, c.biz_no, c.ceo, c.address, c.email),
        )
        return {"id": cur.lastrowid, **c.model_dump()}


@app.get("/api/invoices")
def list_invoices(customer_id: int | None = None):
    sql = (
        "SELECT i.id, i.invoice_no, i.issue_date, i.supply_total, i.tax_total, i.grand_total, i.memo,"
        " c.name AS customer_name FROM invoices i JOIN customers c ON c.id = i.customer_id"
    )
    args = []
    if customer_id:
        sql += " WHERE i.customer_id = ?"
        args.append(customer_id)
    sql += " ORDER BY i.issue_date DESC, i.id DESC"
    with db() as con:
        return [dict(r) for r in con.execute(sql, args)]


@app.get("/api/invoices/{inv_id}")
def get_invoice(inv_id: int):
    with db() as con:
        return load_invoice(con, inv_id)


@app.post("/api/invoices", status_code=201)
def create_invoice(body: InvoiceIn):
    with db() as con:
        check_customer(con, body.customer_id)
        inv_id = insert_invoice(
            con, body.issue_date.isoformat(), body.customer_id, body.memo, [i.model_dump() for i in body.items]
        )
        con.commit()
        return load_invoice(con, inv_id)


@app.put("/api/invoices/{inv_id}")
def update_invoice(inv_id: int, body: InvoiceIn):
    with db() as con:
        load_invoice(con, inv_id)
        check_customer(con, body.customer_id)
        rows, s, t = calc([i.model_dump() for i in body.items])
        con.execute(
            "UPDATE invoices SET issue_date=?, customer_id=?, supply_total=?, tax_total=?, grand_total=?,"
            " memo=?, updated_at=datetime('now','localtime') WHERE id=?",
            (body.issue_date.isoformat(), body.customer_id, s, t, s + t, body.memo, inv_id),
        )
        con.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (inv_id,))
        con.executemany(
            "INSERT INTO invoice_items(invoice_id, name, spec, qty, unit_price, taxable, supply, tax)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [(inv_id, r["name"], r["spec"], r["qty"], r["unit_price"], int(r["taxable"]), r["supply"], r["tax"]) for r in rows],
        )
        con.commit()
        return load_invoice(con, inv_id)


@app.delete("/api/invoices/{inv_id}", status_code=204)
def delete_invoice(inv_id: int):
    with db() as con:
        load_invoice(con, inv_id)
        con.execute("DELETE FROM invoices WHERE id = ?", (inv_id,))
        con.commit()


@app.get("/api/config")
def config():
    return {"tax_rate": TAX_RATE, "supplier": SUPPLIER, "products": [
        {"name": n, "spec": s, "unit_price": p, "taxable": bool(t)} for n, s, p, t in PRODUCTS
    ]}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


init_db()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
