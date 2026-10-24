import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB = BASE / "invoices.db"
TAX_RATE = 10  # 부가세 10%

app = FastAPI(title="가나다식품 세금계산서")


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, biz_no TEXT NOT NULL,
  ceo TEXT, address TEXT, email TEXT);
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  customer_name TEXT NOT NULL, customer_biz_no TEXT NOT NULL,
  issue_date TEXT NOT NULL, supply INTEGER NOT NULL, tax INTEGER NOT NULL,
  total INTEGER NOT NULL, memo TEXT DEFAULT '', status TEXT NOT NULL DEFAULT '발행',
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, name TEXT NOT NULL, spec TEXT DEFAULT '',
  qty INTEGER NOT NULL, unit_price INTEGER NOT NULL, taxable INTEGER NOT NULL DEFAULT 1,
  supply INTEGER NOT NULL);
"""


class Item(BaseModel):
    name: str = Field(min_length=1)
    spec: str = ""
    qty: int = Field(gt=0)
    unit_price: int = Field(ge=0)
    taxable: bool = True


class InvoiceIn(BaseModel):
    customer_id: int
    issue_date: date
    memo: str = ""
    items: list[Item] = Field(min_length=1)


def calc(items):
    """공급가액 = 수량×단가 합계, 세액 = 과세 공급가액 합계 × 10% (원 미만 절사)."""
    lines = [i.qty * i.unit_price for i in items]
    supply = sum(lines)
    taxable = sum(s for s, i in zip(lines, items) if i.taxable)
    tax = taxable * TAX_RATE // 100
    return lines, supply, tax, supply + tax


def next_number(con, d):
    prefix = d.strftime("%Y%m%d")
    n = con.execute("SELECT COUNT(*) FROM invoices WHERE number LIKE ?", (prefix + "-%",)).fetchone()[0]
    while True:
        n += 1
        num = f"{prefix}-{n:03d}"
        if not con.execute("SELECT 1 FROM invoices WHERE number=?", (num,)).fetchone():
            return num


def write_items(con, inv_id, items, lines):
    con.execute("DELETE FROM items WHERE invoice_id=?", (inv_id,))
    con.executemany(
        "INSERT INTO items(invoice_id,seq,name,spec,qty,unit_price,taxable,supply) VALUES(?,?,?,?,?,?,?,?)",
        [(inv_id, k + 1, i.name, i.spec, i.qty, i.unit_price, int(i.taxable), s)
         for k, (i, s) in enumerate(zip(items, lines))])


def get_customer(con, cid):
    c = con.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not c:
        raise HTTPException(404, "거래처를 찾을 수 없습니다")
    return c


def detail(con, inv_id):
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
    if not inv:
        raise HTTPException(404, "계산서를 찾을 수 없습니다")
    out = dict(inv)
    out["items"] = [dict(r) for r in con.execute(
        "SELECT name,spec,qty,unit_price,taxable,supply FROM items WHERE invoice_id=? ORDER BY seq", (inv_id,))]
    return out


@app.get("/api/customers")
def customers():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM customers ORDER BY name")]


@app.get("/api/invoices")
def invoices(q: str = ""):
    with db() as con:
        like = f"%{q}%"
        rows = con.execute(
            "SELECT * FROM invoices WHERE customer_name LIKE ? OR number LIKE ? ORDER BY issue_date DESC, id DESC",
            (like, like))
        return [dict(r) for r in rows]


@app.get("/api/invoices/{inv_id}")
def get_invoice(inv_id: int):
    with db() as con:
        return detail(con, inv_id)


@app.post("/api/invoices", status_code=201)
def create_invoice(body: InvoiceIn):
    lines, supply, tax, total = calc(body.items)
    with db() as con:
        c = get_customer(con, body.customer_id)
        cur = con.execute(
            "INSERT INTO invoices(number,customer_id,customer_name,customer_biz_no,issue_date,supply,tax,total,memo)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (next_number(con, body.issue_date), c["id"], c["name"], c["biz_no"],
             body.issue_date.isoformat(), supply, tax, total, body.memo))
        write_items(con, cur.lastrowid, body.items, lines)
        return detail(con, cur.lastrowid)


@app.put("/api/invoices/{inv_id}")
def update_invoice(inv_id: int, body: InvoiceIn):
    lines, supply, tax, total = calc(body.items)
    with db() as con:
        cur = detail(con, inv_id)
        if cur["status"] == "취소":
            raise HTTPException(409, "취소된 계산서는 수정할 수 없습니다")
        c = get_customer(con, body.customer_id)
        con.execute(
            "UPDATE invoices SET customer_id=?,customer_name=?,customer_biz_no=?,issue_date=?,supply=?,tax=?,"
            "total=?,memo=?,status='수정',updated_at=datetime('now','localtime') WHERE id=?",
            (c["id"], c["name"], c["biz_no"], body.issue_date.isoformat(), supply, tax, total, body.memo, inv_id))
        write_items(con, inv_id, body.items, lines)
        return detail(con, inv_id)


@app.post("/api/invoices/{inv_id}/cancel")
def cancel_invoice(inv_id: int):
    with db() as con:
        detail(con, inv_id)
        con.execute("UPDATE invoices SET status='취소', updated_at=datetime('now','localtime') WHERE id=?", (inv_id,))
        return detail(con, inv_id)


def seed():
    with db() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM customers").fetchone()[0]:
            return
        con.executemany("INSERT INTO customers(name,biz_no,ceo,address,email) VALUES(?,?,?,?,?)", [
            ("한빛마트", "123-45-67890", "김한빛", "서울 마포구 월드컵로 12", "hanbit@example.com"),
            ("초록유통", "211-86-12345", "박초록", "경기 성남시 분당구 판교로 88", "green@example.com"),
            ("행복식자재", "305-81-55021", "이행복", "대전 유성구 대학로 99", "happy@example.com"),
            ("바다횟집", "412-02-77310", "최바다", "부산 해운대구 해변로 7", "sea@example.com"),
            ("든든급식", "508-87-23456", "정든든", "인천 남동구 인주대로 301", "full@example.com"),
            ("맛고을푸드", "617-81-90817", "오맛고", "광주 서구 상무중앙로 45", "matgol@example.com"),
        ])
        products = [  # (품목, 규격, 단가, 과세)
            ("국산 김치", "10kg", 48000, True), ("냉동 만두", "1.5kg", 9800, True),
            ("고추장", "3kg", 18500, True), ("된장", "3kg", 15000, True),
            ("쌀(20kg)", "20kg", 62000, False), ("국산 배추", "10kg", 14000, False),
            ("참기름", "500ml", 13500, True), ("두부", "300g", 1800, False),
            ("어묵", "1kg", 7200, True), ("깐마늘", "1kg", 11000, False),
        ]
        rnd = random.Random(78)
        today = date.today()
        for k in range(14):
            d = today - timedelta(days=k * 2 + rnd.randint(0, 1))
            cid = rnd.randint(1, 6)
            c = con.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
            items = [Item(name=p[0], spec=p[1], qty=rnd.randint(2, 40), unit_price=p[2], taxable=p[3])
                     for p in rnd.sample(products, rnd.randint(1, 4))]
            lines, supply, tax, total = calc(items)
            cur = con.execute(
                "INSERT INTO invoices(number,customer_id,customer_name,customer_biz_no,issue_date,supply,tax,total,memo)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (next_number(con, d), cid, c["name"], c["biz_no"], d.isoformat(), supply, tax, total, ""))
            write_items(con, cur.lastrowid, items, lines)


seed()
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
