import sqlite3
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = BASE / "tax.db"
TAX_RATE_PCT = 10

app = FastAPI(title="가나다식품 세금계산서")


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS partners(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, biz_no TEXT NOT NULL, ceo TEXT, address TEXT, email TEXT);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, spec TEXT, unit_price INTEGER NOT NULL, taxable INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT UNIQUE NOT NULL,
  partner_id INTEGER NOT NULL REFERENCES partners(id),
  issue_date TEXT NOT NULL, memo TEXT,
  supply_amount INTEGER NOT NULL, tax_amount INTEGER NOT NULL, total_amount INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS invoice_lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  name TEXT NOT NULL, spec TEXT, qty INTEGER NOT NULL, unit_price INTEGER NOT NULL,
  taxable INTEGER NOT NULL DEFAULT 1,
  supply_amount INTEGER NOT NULL, tax_amount INTEGER NOT NULL);
"""

PARTNERS = [
    ("한빛마트", "123-45-67890", "김한빛", "서울 강남구 테헤란로 101", "hanbit@example.com"),
    ("푸른유통", "234-56-78901", "이푸른", "경기 성남시 분당구 판교로 22", "purun@example.com"),
    ("바다횟집", "345-67-89012", "박바다", "부산 해운대구 해변로 7", "bada@example.com"),
    ("행복급식(주)", "456-78-90123", "최행복", "대전 유성구 대학로 55", "happy@example.com"),
    ("온누리슈퍼", "567-89-01234", "정온누리", "광주 서구 상무중앙로 9", "onnuri@example.com"),
]
PRODUCTS = [
    ("국산 쌀 20kg", "포대", 52000, 0), ("깐마늘 1kg", "봉", 9800, 0),
    ("냉동만두 1.2kg", "봉", 8900, 1), ("참기름 500ml", "병", 15500, 1),
    ("고추장 3kg", "통", 18900, 1), ("김치 5kg", "박스", 27000, 1),
    ("두부 300g", "모", 1800, 0), ("식용유 18L", "캔", 48000, 1),
]


def calc_line(qty, price, taxable):
    supply = qty * price
    tax = (supply * TAX_RATE_PCT + 50) // 100 if taxable else 0  # 원 단위 반올림, 면세 품목은 0
    return supply, tax


def write_invoice(con, iid, partner_id, issue_date, memo, lines):
    """iid가 None이면 신규 발행, 아니면 해당 계산서의 내용을 교체(수정)한다."""
    if not lines:
        raise HTTPException(400, "품목을 1줄 이상 입력하세요")
    if not con.execute("SELECT 1 FROM partners WHERE id=?", (partner_id,)).fetchone():
        raise HTTPException(400, "거래처를 찾을 수 없습니다")
    rows, S, T = [], 0, 0
    for l in lines:
        s, t = calc_line(l["qty"], l["unit_price"], l["taxable"])
        rows.append((l["name"], l.get("spec"), l["qty"], l["unit_price"], int(l["taxable"]), s, t))
        S += s
        T += t
    if iid is None:
        ym = issue_date.replace("-", "")
        n = con.execute("SELECT COUNT(*) FROM invoices WHERE invoice_no LIKE ?", (ym + "-%",)).fetchone()[0] + 1
        while con.execute("SELECT 1 FROM invoices WHERE invoice_no=?", (f"{ym}-{n:04d}",)).fetchone():
            n += 1
        iid = con.execute(
            "INSERT INTO invoices(invoice_no,partner_id,issue_date,memo,supply_amount,tax_amount,total_amount)"
            " VALUES(?,?,?,?,?,?,?)", (f"{ym}-{n:04d}", partner_id, issue_date, memo, S, T, S + T)).lastrowid
    else:
        con.execute(
            "UPDATE invoices SET partner_id=?,issue_date=?,memo=?,supply_amount=?,tax_amount=?,total_amount=?,"
            "updated_at=CURRENT_TIMESTAMP WHERE id=?", (partner_id, issue_date, memo, S, T, S + T, iid))
        con.execute("DELETE FROM invoice_lines WHERE invoice_id=?", (iid,))
    con.executemany(
        "INSERT INTO invoice_lines(invoice_id,name,spec,qty,unit_price,taxable,supply_amount,tax_amount)"
        " VALUES(?,?,?,?,?,?,?,?)", [(iid, *r) for r in rows])
    return iid


@app.on_event("startup")
def init():
    con = db()
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM partners").fetchone():
        con.executemany("INSERT INTO partners(name,biz_no,ceo,address,email) VALUES(?,?,?,?,?)", PARTNERS)
        con.executemany("INSERT INTO products(name,spec,unit_price,taxable) VALUES(?,?,?,?)", PRODUCTS)
        seed = [
            (1, "2026-09-03", "9월 1차 납품", [(2, 10), (3, 30), (4, 12)]),
            (2, "2026-09-15", "", [(1, 5), (6, 20)]),
            (3, "2026-09-28", "수산시장 행사", [(8, 4), (4, 6), (5, 3)]),
            (4, "2026-10-05", "급식 정기납품", [(1, 20), (7, 200), (2, 25)]),
            (1, "2026-10-12", "", [(3, 50), (6, 15)]),
            (5, "2026-10-20", "추석 이후 재고 보충", [(5, 10), (4, 8), (8, 2)]),
        ]
        prods = {r["id"]: r for r in con.execute("SELECT * FROM products")}
        for pid, d, memo, items in seed:
            lines = [dict(name=prods[i]["name"], spec=prods[i]["spec"], qty=q,
                          unit_price=prods[i]["unit_price"], taxable=bool(prods[i]["taxable"]))
                     for i, q in items]
            write_invoice(con, None, pid, d, memo, lines)
        con.commit()
    con.close()


class Line(BaseModel):
    name: str = Field(min_length=1)
    spec: Optional[str] = None
    qty: int = Field(gt=0)
    unit_price: int = Field(ge=0)
    taxable: bool = True


class InvoiceIn(BaseModel):
    partner_id: int
    issue_date: date
    memo: Optional[str] = ""
    lines: List[Line]


def full_invoice(con, iid):
    inv = con.execute(
        "SELECT i.*, p.name AS partner_name, p.biz_no, p.ceo, p.address, p.email"
        " FROM invoices i JOIN partners p ON p.id=i.partner_id WHERE i.id=?", (iid,)).fetchone()
    if not inv:
        raise HTTPException(404, "계산서를 찾을 수 없습니다")
    d = dict(inv)
    d["lines"] = [dict(r) | {"taxable": bool(r["taxable"])}
                  for r in con.execute("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id", (iid,))]
    return d


@app.get("/api/partners")
def partners():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM partners ORDER BY name")]


@app.get("/api/products")
def products():
    with db() as con:
        return [dict(r) | {"taxable": bool(r["taxable"])} for r in con.execute("SELECT * FROM products ORDER BY id")]


@app.get("/api/invoices")
def list_invoices(q: str = ""):
    sql = ("SELECT i.id,i.invoice_no,i.issue_date,i.memo,i.supply_amount,i.tax_amount,i.total_amount,"
           "p.name AS partner_name FROM invoices i JOIN partners p ON p.id=i.partner_id")
    args = ()
    if q:
        sql += " WHERE p.name LIKE ? OR i.invoice_no LIKE ?"
        args = (f"%{q}%", f"%{q}%")
    sql += " ORDER BY i.issue_date DESC, i.id DESC"
    with db() as con:
        return [dict(r) for r in con.execute(sql, args)]


@app.get("/api/invoices/{iid}")
def get_invoice(iid: int):
    with db() as con:
        return full_invoice(con, iid)


@app.post("/api/invoices", status_code=201)
def create_invoice(body: InvoiceIn):
    with db() as con:
        iid = write_invoice(con, None, body.partner_id, body.issue_date.isoformat(), body.memo,
                            [l.model_dump() for l in body.lines])
        con.commit()
        return full_invoice(con, iid)


@app.put("/api/invoices/{iid}")
def update_invoice(iid: int, body: InvoiceIn):
    with db() as con:
        if not con.execute("SELECT 1 FROM invoices WHERE id=?", (iid,)).fetchone():
            raise HTTPException(404, "계산서를 찾을 수 없습니다")
        write_invoice(con, iid, body.partner_id, body.issue_date.isoformat(), body.memo,
                      [l.model_dump() for l in body.lines])
        con.commit()
        return full_invoice(con, iid)


@app.delete("/api/invoices/{iid}", status_code=204)
def delete_invoice(iid: int):
    with db() as con:
        if not con.execute("DELETE FROM invoices WHERE id=?", (iid,)).rowcount:
            raise HTTPException(404, "계산서를 찾을 수 없습니다")
        con.commit()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
