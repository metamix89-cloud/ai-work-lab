import csv
import datetime as dt
import os
import re
import sqlite3
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "invoice.db")
LOCK = threading.Lock()
app = FastAPI()
BAD = "필수 항목을 확인하세요"


class Reject(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    c = conn()
    c.executescript("""
    CREATE TABLE tx_customers (biz_no TEXT PRIMARY KEY, name TEXT, ceo TEXT);
    CREATE TABLE tx_invoices (invoice_no TEXT PRIMARY KEY, issued TEXT, biz_no TEXT, supply INTEGER, tax INTEGER,
        total INTEGER, status TEXT, amends TEXT, amended_by TEXT);
    CREATE TABLE tx_lines (invoice_no TEXT, line INTEGER, item TEXT, qty INTEGER, unit_price INTEGER,
        PRIMARY KEY (invoice_no, line));
    """)
    for r in read_csv("customers.csv"):
        c.execute("INSERT INTO tx_customers VALUES (?,?,?)", (r["biz_no"], r["name"], r["ceo"]))
    for r in read_csv("invoices.csv"):
        c.execute("INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)",
                  (r["invoice_no"], r["issued"], r["biz_no"], int(r["supply"]), int(r["tax"]), int(r["total"]),
                   r["status"], r["amends"] or "", r["amended_by"] or ""))
    for r in read_csv("invoice_lines.csv"):
        c.execute("INSERT INTO tx_lines VALUES (?,?,?,?,?)",
                  (r["invoice_no"], int(r["line"]), r["item"], int(r["qty"]), int(r["unit_price"])))
    c.commit()
    c.close()


init_db()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        raise Reject(400, BAD + " (본문)")
    if not isinstance(b, dict):
        raise Reject(400, BAD + " (본문)")
    return b


def check_date(v):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise Reject(400, BAD + " (작성일)")
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        raise Reject(400, BAD + " (작성일)")


def check_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise Reject(400, BAD + " (품목)")
    out = []
    for i, l in enumerate(lines, 1):
        if not isinstance(l, dict):
            raise Reject(400, BAD + " (품목 %d)" % i)
        item, qty, price = l.get("item"), l.get("qty"), l.get("unit_price")
        if not isinstance(item, str) or not item.strip():
            raise Reject(400, BAD + " (품목 %d 품목명)" % i)
        if not is_int(qty) or qty < 1:
            raise Reject(400, BAD + " (품목 %d 수량)" % i)
        if not is_int(price) or price < 0:
            raise Reject(400, BAD + " (품목 %d 단가)" % i)
        out.append((item.strip(), qty, price))
    return out


def compute(lines):
    supply = sum(q * p for _, q, p in lines)
    tax = supply * 10 // 100
    return supply, tax, supply + tax


def customer_of(c, biz):
    return c.execute("SELECT * FROM tx_customers WHERE biz_no=?", (biz,)).fetchone()


def check_new(c, b):
    biz = b.get("biz_no")
    if not isinstance(biz, str) or not customer_of(c, biz):
        raise Reject(400, BAD + " (거래처)")
    check_date(b.get("issued"))
    return biz, b["issued"], check_lines(b.get("lines"))


def next_no(c, issued):
    prefix = "INV-%s-" % issued.replace("-", "")
    n = 0
    for (no,) in c.execute("SELECT invoice_no FROM tx_invoices WHERE invoice_no LIKE ?", (prefix + "%",)):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", no)
        if m:
            n = max(n, int(m.group(1)))
    return "%s%03d" % (prefix, n + 1)


def invoice_dict(c, row, with_lines=True):
    cu = customer_of(c, row["biz_no"])
    d = {"invoice_no": row["invoice_no"], "issued": row["issued"], "biz_no": row["biz_no"],
         "customer": cu["name"] if cu else "", "supply": row["supply"], "tax": row["tax"], "total": row["total"],
         "status": row["status"], "amends": row["amends"] or "", "amended_by": row["amended_by"] or ""}
    if with_lines:
        d["lines"] = [{"line": r["line"], "item": r["item"], "qty": r["qty"], "unit_price": r["unit_price"],
                       "line_supply": r["qty"] * r["unit_price"]}
                      for r in c.execute("SELECT * FROM tx_lines WHERE invoice_no=? ORDER BY line", (row["invoice_no"],))]
    return d


def insert_invoice(c, biz, issued, lines, amends=""):
    no = next_no(c, issued)
    supply, tax, total = compute(lines)
    c.execute("INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)", (no, issued, biz, supply, tax, total, "발행", amends, ""))
    for n, (i, q, p) in enumerate(lines, 1):
        c.execute("INSERT INTO tx_lines VALUES (?,?,?,?,?)", (no, n, i, q, p))
    return no


def get_row(c, no):
    row = c.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone()
    if not row:
        raise Reject(404, "계산서를 찾을 수 없습니다")
    return row


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/customers")
def customers():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM tx_customers ORDER BY biz_no")]
    finally:
        c.close()


@app.post("/api/invoices/preview")
async def preview(request: Request):
    b = await body_of(request)
    c = conn()
    try:
        _, _, lines = check_new(c, b)
    finally:
        c.close()
    supply, tax, total = compute(lines)
    return {"supply": supply, "tax": tax, "total": total,
            "lines": [{"item": i, "qty": q, "unit_price": p, "line_supply": q * p} for i, q, p in lines]}


@app.post("/api/invoices")
async def create(request: Request):
    b = await body_of(request)
    with LOCK:
        c = conn()
        try:
            biz, issued, lines = check_new(c, b)
            no = insert_invoice(c, biz, issued, lines)
            c.commit()
            return JSONResponse(invoice_dict(c, get_row(c, no)), status_code=201)
        finally:
            c.close()


@app.get("/api/invoices")
def ledger(month: str = ""):
    if not month:
        month = dt.date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise Reject(400, "month 형식은 YYYY-MM 입니다")
    c = conn()
    try:
        rows = c.execute("SELECT * FROM tx_invoices WHERE issued LIKE ? ORDER BY invoice_no", (month + "-%",)).fetchall()
        s = sum(r["supply"] for r in rows if r["status"] == "발행")
        t = sum(r["tax"] for r in rows if r["status"] == "발행")
        return {"month": month, "count": len(rows), "totals": {"supply": s, "tax": t, "total": s + t},
                "items": [invoice_dict(c, r, False) for r in rows]}
    finally:
        c.close()


@app.get("/api/invoices/{no}")
def detail(no: str):
    c = conn()
    try:
        return invoice_dict(c, get_row(c, no))
    finally:
        c.close()


@app.post("/api/invoices/{no}/amend")
async def amend(no: str, request: Request):
    b = await body_of(request)
    check_date(b.get("issued"))
    lines = check_lines(b.get("lines"))
    with LOCK:
        c = conn()
        try:
            orig = get_row(c, no)
            if orig["status"] != "발행":
                raise Reject(409, "발행 상태가 아닙니다")
            new = insert_invoice(c, orig["biz_no"], b["issued"], lines, amends=no)
            c.execute("UPDATE tx_invoices SET status='수정됨', amended_by=? WHERE invoice_no=?", (new, no))
            c.commit()
            return JSONResponse(invoice_dict(c, get_row(c, new)), status_code=201)
        finally:
            c.close()


@app.post("/api/invoices/{no}/cancel")
def cancel(no: str):
    with LOCK:
        c = conn()
        try:
            row = get_row(c, no)
            if row["status"] != "발행":
                raise Reject(409, "발행 상태가 아닙니다")
            c.execute("UPDATE tx_invoices SET status='취소' WHERE invoice_no=?", (no,))
            c.commit()
            return invoice_dict(c, get_row(c, no))
        finally:
            c.close()
