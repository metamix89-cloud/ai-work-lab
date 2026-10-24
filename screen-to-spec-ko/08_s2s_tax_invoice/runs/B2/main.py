import csv
import os
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB_PATH = BASE / "invoice.db"
LOCK = threading.RLock()
INVALID = "필수 항목을 확인하세요"
NOT_ISSUED = "발행 상태가 아닙니다"
NOT_FOUND = "계산서를 찾을 수 없습니다"

app = FastAPI()


class Reject(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


@app.exception_handler(Reject)
async def reject_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE tx_customers (biz_no TEXT PRIMARY KEY, name TEXT, ceo TEXT);
        CREATE TABLE tx_invoices (
            invoice_no TEXT PRIMARY KEY, issued TEXT, biz_no TEXT,
            supply INTEGER, tax INTEGER, total INTEGER, status TEXT,
            amends TEXT, amended_by TEXT);
        CREATE TABLE tx_lines (
            invoice_no TEXT, line INTEGER, item TEXT, qty INTEGER, unit_price INTEGER,
            PRIMARY KEY (invoice_no, line));
        """
    )
    for r in read_csv("customers.csv"):
        db.execute("INSERT INTO tx_customers VALUES (?,?,?)", (r["biz_no"], r["name"], r["ceo"]))
    for r in read_csv("invoices.csv"):
        db.execute(
            "INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)",
            (r["invoice_no"], r["issued"], r["biz_no"], int(r["supply"]), int(r["tax"]),
             int(r["total"]), r["status"], r["amends"] or None, r["amended_by"] or None),
        )
    for r in read_csv("invoice_lines.csv"):
        db.execute(
            "INSERT INTO tx_lines VALUES (?,?,?,?,?)",
            (r["invoice_no"], int(r["line"]), r["item"], int(r["qty"]), int(r["unit_price"])),
        )
    db.commit()
    return db


DB = init_db()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def valid_date(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def bad(what):
    return Reject(400, f"{INVALID} ({what})")


def clean_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise bad("품목 줄")
    out = []
    for i, ln in enumerate(lines, 1):
        if not isinstance(ln, dict):
            raise bad(f"{i}번째 줄")
        item, qty, price = ln.get("item"), ln.get("qty"), ln.get("unit_price")
        if not isinstance(item, str) or not item.strip():
            raise bad(f"{i}번째 줄 품목명")
        if not is_int(qty) or qty < 1:
            raise bad(f"{i}번째 줄 수량")
        if not is_int(price) or price < 0:
            raise bad(f"{i}번째 줄 단가")
        out.append({"item": item.strip(), "qty": qty, "unit_price": price})
    return out


def compute(lines):
    """R1: 정수 연산. 세액은 공급가 합계에 한 번만 매긴다."""
    rows = [{**ln, "line_supply": ln["qty"] * ln["unit_price"]} for ln in lines]
    supply = sum(r["line_supply"] for r in rows)
    tax = supply * 10 // 100
    return {"supply": supply, "tax": tax, "total": supply + tax, "lines": rows}


async def body_of(request):
    try:
        body = await request.json()
    except Exception:
        raise Reject(400, INVALID)
    if not isinstance(body, dict):
        raise Reject(400, INVALID)
    return body


def customer_of(biz_no):
    if not isinstance(biz_no, str):
        return None
    return DB.execute("SELECT * FROM tx_customers WHERE biz_no=?", (biz_no,)).fetchone()


def validate_new(body):
    if customer_of(body.get("biz_no")) is None:
        raise bad("거래처")
    if not valid_date(body.get("issued")):
        raise bad("작성일")
    return clean_lines(body.get("lines"))


def next_no(issued):
    prefix = "INV-" + issued.replace("-", "") + "-"
    rows = DB.execute("SELECT invoice_no FROM tx_invoices WHERE invoice_no LIKE ?", (prefix + "%",)).fetchall()
    seqs = [int(r["invoice_no"][len(prefix):]) for r in rows if r["invoice_no"][len(prefix):].isdigit()]
    return f"{prefix}{max(seqs, default=0) + 1:03d}"


def present(row, with_lines):
    d = dict(row)
    c = customer_of(d["biz_no"])
    d["customer"] = c["name"] if c else ""
    if with_lines:
        ls = DB.execute(
            "SELECT item, qty, unit_price FROM tx_lines WHERE invoice_no=? ORDER BY line", (d["invoice_no"],)
        ).fetchall()
        d["lines"] = [{**dict(l), "line_supply": l["qty"] * l["unit_price"]} for l in ls]
    return d


def insert_invoice(biz_no, issued, lines, amends=None):
    calc = compute(lines)
    no = next_no(issued)
    DB.execute(
        "INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)",
        (no, issued, biz_no, calc["supply"], calc["tax"], calc["total"], "발행", amends, None),
    )
    for i, ln in enumerate(lines, 1):
        DB.execute("INSERT INTO tx_lines VALUES (?,?,?,?,?)", (no, i, ln["item"], ln["qty"], ln["unit_price"]))
    return no


def get_row(no):
    return DB.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/customers")
def customers():
    with LOCK:
        return [dict(r) for r in DB.execute("SELECT * FROM tx_customers ORDER BY biz_no")]


@app.post("/api/invoices/preview")
async def preview(request: Request):
    body = await body_of(request)
    with LOCK:
        lines = validate_new(body)
    return compute(lines)


@app.post("/api/invoices")
async def create(request: Request):
    body = await body_of(request)
    with LOCK:
        lines = validate_new(body)
        try:
            no = insert_invoice(body["biz_no"], body["issued"], lines)
            DB.commit()
        except Exception:
            DB.rollback()
            raise
        return JSONResponse(present(get_row(no), True), status_code=201)


@app.get("/api/invoices")
def list_invoices(month: str = None):
    if month is None:
        month = date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise Reject(400, INVALID)
    with LOCK:
        rows = DB.execute(
            "SELECT * FROM tx_invoices WHERE substr(issued,1,7)=? ORDER BY invoice_no", (month,)
        ).fetchall()
        items = [present(r, False) for r in rows]
    ok = [i for i in items if i["status"] == "발행"]
    totals = {k: sum(i[k] for i in ok) for k in ("supply", "tax", "total")}
    return {"month": month, "count": len(items), "totals": totals, "items": items}


@app.get("/api/invoices/{no}")
def detail(no: str):
    with LOCK:
        row = get_row(no)
        if row is None:
            raise Reject(404, NOT_FOUND)
        return present(row, True)


@app.post("/api/invoices/{no}/amend")
async def amend(no: str, request: Request):
    body = await body_of(request)
    if not valid_date(body.get("issued")):
        raise bad("작성일")
    lines = clean_lines(body.get("lines"))
    with LOCK:
        row = get_row(no)
        if row is None:
            raise Reject(404, NOT_FOUND)
        if row["status"] != "발행":
            raise Reject(409, NOT_ISSUED)
        try:
            new_no = insert_invoice(row["biz_no"], body["issued"], lines, amends=no)
            DB.execute("UPDATE tx_invoices SET status='수정됨', amended_by=? WHERE invoice_no=?", (new_no, no))
            DB.commit()
        except Exception:
            DB.rollback()
            raise
        return JSONResponse(present(get_row(new_no), True), status_code=201)


@app.post("/api/invoices/{no}/cancel")
def cancel(no: str):
    with LOCK:
        row = get_row(no)
        if row is None:
            raise Reject(404, NOT_FOUND)
        if row["status"] != "발행":
            raise Reject(409, NOT_ISSUED)
        DB.execute("UPDATE tx_invoices SET status='취소' WHERE invoice_no=?", (no,))
        DB.commit()
        return present(get_row(no), True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
