import csv
import datetime as dt
import os
import re
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "invoice.db")
SEED = os.path.join(ROOT, "seed")

app = FastAPI()


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def read_csv(name):
    with open(os.path.join(SEED, name), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    if os.path.exists(DB):
        os.remove(DB)
    c = conn()
    c.executescript("""
    CREATE TABLE tx_customers (biz_no TEXT PRIMARY KEY, name TEXT, ceo TEXT);
    CREATE TABLE tx_invoices (invoice_no TEXT PRIMARY KEY, issued TEXT, biz_no TEXT,
        supply INTEGER, tax INTEGER, total INTEGER, status TEXT, amends TEXT, amended_by TEXT);
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


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


BAD = "필수 항목을 확인하세요"


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


def check_issued(v):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise Reject(400, BAD + " (작성일)")
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        raise Reject(400, BAD + " (작성일)")


def clean_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise Reject(400, BAD + " (품목)")
    out = []
    for i, l in enumerate(lines, 1):
        if not isinstance(l, dict):
            raise Reject(400, BAD + " (품목 %d줄)" % i)
        item, qty, price = l.get("item"), l.get("qty"), l.get("unit_price")
        if not isinstance(item, str) or not item.strip():
            raise Reject(400, BAD + " (품목명 %d줄)" % i)
        if not is_int(qty) or qty < 1:
            raise Reject(400, BAD + " (수량 %d줄)" % i)
        if not is_int(price) or price < 0:
            raise Reject(400, BAD + " (단가 %d줄)" % i)
        out.append({"item": item.strip(), "qty": qty, "unit_price": price, "line_supply": qty * price})
    return out


def amounts(lines):
    supply = sum(l["line_supply"] for l in lines)
    tax = supply * 10 // 100
    return supply, tax, supply + tax


def customer_of(c, biz):
    if not isinstance(biz, str):
        return None
    return c.execute("SELECT * FROM tx_customers WHERE biz_no=?", (biz,)).fetchone()


def shape(c, row, with_lines=True):
    cust = c.execute("SELECT name FROM tx_customers WHERE biz_no=?", (row["biz_no"],)).fetchone()
    d = {"invoice_no": row["invoice_no"], "issued": row["issued"], "biz_no": row["biz_no"],
         "customer": cust["name"] if cust else "", "supply": row["supply"], "tax": row["tax"],
         "total": row["total"], "status": row["status"], "amends": row["amends"], "amended_by": row["amended_by"]}
    if with_lines:
        d["lines"] = [{"item": l["item"], "qty": l["qty"], "unit_price": l["unit_price"],
                       "line_supply": l["qty"] * l["unit_price"]}
                      for l in c.execute("SELECT * FROM tx_lines WHERE invoice_no=? ORDER BY line", (row["invoice_no"],))]
    return d


def next_no(c, issued):
    prefix = "INV-" + issued.replace("-", "") + "-"
    mx = 0
    for r in c.execute("SELECT invoice_no FROM tx_invoices WHERE invoice_no LIKE ?", (prefix + "%",)):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", r["invoice_no"])
        if m:
            mx = max(mx, int(m.group(1)))
    return "%s%03d" % (prefix, mx + 1)


def insert(c, no, issued, biz, lines, amends=""):
    supply, tax, total = amounts(lines)
    c.execute("INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)", (no, issued, biz, supply, tax, total, "발행", amends, ""))
    for i, l in enumerate(lines, 1):
        c.execute("INSERT INTO tx_lines VALUES (?,?,?,?,?)", (no, i, l["item"], l["qty"], l["unit_price"]))


def load(c, no):
    row = c.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone()
    if not row:
        raise Reject(404, "계산서를 찾을 수 없습니다")
    return row


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"))


@app.get("/api/customers")
def customers():
    c = conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM tx_customers ORDER BY biz_no")]
    c.close()
    return rows


async def validated_new(request):
    b = await body_of(request)
    check_issued(b.get("issued"))
    lines = clean_lines(b.get("lines"))
    c = conn()
    if not customer_of(c, b.get("biz_no")):
        c.close()
        raise Reject(400, BAD + " (거래처)")
    return c, b, lines


@app.post("/api/invoices/preview")
async def preview(request: Request):
    c, b, lines = await validated_new(request)
    c.close()
    supply, tax, total = amounts(lines)
    return {"supply": supply, "tax": tax, "total": total, "lines": lines}


@app.post("/api/invoices")
async def create(request: Request):
    c, b, lines = await validated_new(request)
    try:
        no = next_no(c, b["issued"])
        insert(c, no, b["issued"], b["biz_no"], lines)
        c.commit()
        row = c.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone()
        return JSONResponse(shape(c, row), status_code=201)
    finally:
        c.close()


@app.get("/api/invoices")
def ledger(month: str = ""):
    if not month:
        month = dt.date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise Reject(400, "month 형식은 YYYY-MM 입니다")
    c = conn()
    rows = c.execute("SELECT * FROM tx_invoices WHERE issued LIKE ? ORDER BY invoice_no", (month + "-%",)).fetchall()
    items = [shape(c, r, False) for r in rows]
    c.close()
    ok = [i for i in items if i["status"] == "발행"]
    return {"month": month, "count": len(items),
            "totals": {"supply": sum(i["supply"] for i in ok), "tax": sum(i["tax"] for i in ok),
                       "total": sum(i["total"] for i in ok)},
            "items": items}


@app.get("/api/invoices/{no}")
def detail(no: str):
    c = conn()
    try:
        return shape(c, load(c, no))
    finally:
        c.close()


@app.post("/api/invoices/{no}/amend")
async def amend(no: str, request: Request):
    b = await body_of(request)
    check_issued(b.get("issued"))
    lines = clean_lines(b.get("lines"))
    c = conn()
    try:
        orig = load(c, no)
        if orig["status"] != "발행":
            raise Reject(409, "발행 상태가 아닙니다")
        new = next_no(c, b["issued"])
        insert(c, new, b["issued"], orig["biz_no"], lines, amends=no)
        c.execute("UPDATE tx_invoices SET status='수정됨', amended_by=? WHERE invoice_no=?", (new, no))
        c.commit()
        row = c.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (new,)).fetchone()
        return JSONResponse(shape(c, row), status_code=201)
    finally:
        c.close()


@app.post("/api/invoices/{no}/cancel")
def cancel(no: str):
    c = conn()
    try:
        row = load(c, no)
        if row["status"] != "발행":
            raise Reject(409, "발행 상태가 아닙니다")
        c.execute("UPDATE tx_invoices SET status='취소' WHERE invoice_no=?", (no,))
        c.commit()
        return shape(c, load(c, no))
    finally:
        c.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
