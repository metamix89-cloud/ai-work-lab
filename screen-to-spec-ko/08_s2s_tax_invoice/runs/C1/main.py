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
MSG_REQ = "필수 항목을 확인하세요"

app = FastAPI()


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
    CREATE TABLE tx_lines (invoice_no TEXT, line INTEGER, item TEXT, qty INTEGER, unit_price INTEGER);
    """)
    for r in read_csv("customers.csv"):
        c.execute("INSERT INTO tx_customers VALUES (?,?,?)", (r["biz_no"], r["name"], r["ceo"]))
    for r in read_csv("invoices.csv"):
        c.execute("INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)",
                  (r["invoice_no"], r["issued"], r["biz_no"], int(r["supply"]), int(r["tax"]), int(r["total"]),
                   r["status"], r["amends"], r["amended_by"]))
    for r in read_csv("invoice_lines.csv"):
        c.execute("INSERT INTO tx_lines VALUES (?,?,?,?,?)",
                  (r["invoice_no"], int(r["line"]), r["item"], int(r["qty"]), int(r["unit_price"])))
    c.commit()
    c.close()


init_db()


class Reject(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.code)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def bad(why):
    return Reject(400, "%s: %s" % (MSG_REQ, why))


async def body_of(request):
    try:
        b = await request.json()
    except Exception:
        raise bad("본문")
    if not isinstance(b, dict):
        raise bad("본문")
    return b


def check_issued(v):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise bad("작성일")
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        raise bad("작성일")
    return v


def check_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise bad("품목")
    out = []
    for i, l in enumerate(lines, 1):
        if not isinstance(l, dict):
            raise bad("%d번째 줄" % i)
        item = l.get("item")
        if not isinstance(item, str) or not item.strip():
            raise bad("%d번째 줄 품목명" % i)
        if not is_int(l.get("qty")) or l["qty"] < 1:
            raise bad("%d번째 줄 수량" % i)
        if not is_int(l.get("unit_price")) or l["unit_price"] < 0:
            raise bad("%d번째 줄 단가" % i)
        out.append({"item": item.strip(), "qty": l["qty"], "unit_price": l["unit_price"],
                    "line_supply": l["qty"] * l["unit_price"]})
    return out


def amounts(lines):
    supply = sum(l["line_supply"] for l in lines)
    tax = supply * 10 // 100
    return supply, tax, supply + tax


def customer_of(c, biz):
    return c.execute("SELECT * FROM tx_customers WHERE biz_no=?", (biz,)).fetchone()


def validate_new(c, b):
    biz = b.get("biz_no")
    if not isinstance(biz, str) or customer_of(c, biz) is None:
        raise bad("거래처")
    return biz, check_issued(b.get("issued")), check_lines(b.get("lines"))


def view(c, row, with_lines=True):
    cu = customer_of(c, row["biz_no"])
    d = {"invoice_no": row["invoice_no"], "issued": row["issued"], "biz_no": row["biz_no"],
         "customer": cu["name"] if cu else "", "supply": row["supply"], "tax": row["tax"], "total": row["total"],
         "status": row["status"], "amends": row["amends"] or None, "amended_by": row["amended_by"] or None}
    if with_lines:
        d["lines"] = [{"item": l["item"], "qty": l["qty"], "unit_price": l["unit_price"],
                       "line_supply": l["qty"] * l["unit_price"]}
                      for l in c.execute("SELECT * FROM tx_lines WHERE invoice_no=? ORDER BY line", (row["invoice_no"],))]
    return d


def next_no(c, issued):
    prefix = "INV-%s-" % issued.replace("-", "")
    best = 0
    for (n,) in c.execute("SELECT invoice_no FROM tx_invoices WHERE invoice_no LIKE ?", (prefix + "%",)):
        tail = n[len(prefix):]
        if tail.isdigit():
            best = max(best, int(tail))
    return "%s%03d" % (prefix, best + 1)


def insert(c, issued, biz, lines, amends=""):
    no = next_no(c, issued)
    s, t, tot = amounts(lines)
    c.execute("INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)", (no, issued, biz, s, t, tot, "발행", amends, ""))
    for i, l in enumerate(lines, 1):
        c.execute("INSERT INTO tx_lines VALUES (?,?,?,?,?)", (no, i, l["item"], l["qty"], l["unit_price"]))
    return no


@app.get("/api/customers")
def customers():
    c = conn()
    try:
        return [dict(r) for r in c.execute("SELECT biz_no,name,ceo FROM tx_customers ORDER BY biz_no")]
    finally:
        c.close()


@app.post("/api/invoices/preview")
async def preview(request: Request):
    b = await body_of(request)
    c = conn()
    try:
        _, _, lines = validate_new(c, b)
    finally:
        c.close()
    s, t, tot = amounts(lines)
    return {"supply": s, "tax": t, "total": tot, "lines": lines}


@app.post("/api/invoices", status_code=201)
async def create(request: Request):
    b = await body_of(request)
    with LOCK:
        c = conn()
        try:
            biz, issued, lines = validate_new(c, b)
            no = insert(c, issued, biz, lines)
            c.commit()
            return view(c, c.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone())
        finally:
            c.close()


@app.get("/api/invoices")
def ledger(month: str = None):
    if month is None:
        month = dt.date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise Reject(400, "%s: 월" % MSG_REQ)
    c = conn()
    try:
        rows = c.execute("SELECT * FROM tx_invoices WHERE issued LIKE ? ORDER BY invoice_no", (month + "-%",)).fetchall()
        ok = [r for r in rows if r["status"] == "발행"]
        return {"month": month, "count": len(rows),
                "totals": {"supply": sum(r["supply"] for r in ok), "tax": sum(r["tax"] for r in ok),
                           "total": sum(r["total"] for r in ok)},
                "items": [view(c, r, False) for r in rows]}
    finally:
        c.close()


def find(c, no):
    r = c.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone()
    if r is None:
        raise Reject(404, "계산서를 찾을 수 없습니다")
    return r


@app.get("/api/invoices/{no}")
def detail(no: str):
    c = conn()
    try:
        return view(c, find(c, no))
    finally:
        c.close()


@app.post("/api/invoices/{no}/amend", status_code=201)
async def amend(no: str, request: Request):
    b = await body_of(request)
    issued = check_issued(b.get("issued"))
    lines = check_lines(b.get("lines"))
    with LOCK:
        c = conn()
        try:
            orig = find(c, no)
            if orig["status"] != "발행":
                raise Reject(409, "발행 상태가 아닙니다")
            new = insert(c, issued, orig["biz_no"], lines, amends=no)
            c.execute("UPDATE tx_invoices SET status='수정됨', amended_by=? WHERE invoice_no=?", (new, no))
            c.commit()
            return view(c, find(c, new))
        finally:
            c.close()


@app.post("/api/invoices/{no}/cancel")
def cancel(no: str):
    with LOCK:
        c = conn()
        try:
            r = find(c, no)
            if r["status"] != "발행":
                raise Reject(409, "발행 상태가 아닙니다")
            c.execute("UPDATE tx_invoices SET status='취소' WHERE invoice_no=?", (no,))
            c.commit()
            return view(c, find(c, no))
        finally:
            c.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")
