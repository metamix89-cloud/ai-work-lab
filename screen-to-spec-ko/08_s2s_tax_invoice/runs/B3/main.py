import csv
import os
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.requests import Request

BASE = Path(__file__).parent
SEED = BASE / "seed"
DB_PATH = BASE / "invoice.db"
LOCK = threading.RLock()
BAD = "필수 항목을 확인하세요"
NOT_ISSUED = "발행 상태가 아닙니다"

app = FastAPI()
db = None


class ApiError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    global db
    if db is not None:
        db.close()
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(str(DB_PATH) + suffix)
        except OSError:
            pass
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


init_db()


@app.exception_handler(ApiError)
async def api_error(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def bad(extra=""):
    return ApiError(400, f"{BAD} ({extra})" if extra else BAD)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


async def body_of(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise bad("본문")
    if not isinstance(data, dict):
        raise bad("본문")
    return data


def valid_date(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def parse_common(data):
    """작성일과 품목 줄을 검증해 (issued, lines) 반환. 위반 시 400."""
    issued = data.get("issued")
    if not valid_date(issued):
        raise bad("작성일")
    raw = data.get("lines")
    if not isinstance(raw, list) or not raw:
        raise bad("품목")
    lines = []
    for i, ln in enumerate(raw, 1):
        if not isinstance(ln, dict):
            raise bad(f"{i}번째 줄")
        item, qty, price = ln.get("item"), ln.get("qty"), ln.get("unit_price")
        if not isinstance(item, str) or not item.strip():
            raise bad(f"{i}번째 줄 품목명")
        if not is_int(qty) or qty < 1:
            raise bad(f"{i}번째 줄 수량")
        if not is_int(price) or price < 0:
            raise bad(f"{i}번째 줄 단가")
        lines.append({"item": item.strip(), "qty": qty, "unit_price": price})
    return issued, lines


def customer_of(biz_no):
    if not isinstance(biz_no, str):
        return None
    return db.execute("SELECT * FROM tx_customers WHERE biz_no=?", (biz_no,)).fetchone()


def compute(lines):
    out = []
    for ln in lines:
        out.append({**ln, "line_supply": ln["qty"] * ln["unit_price"]})
    supply = sum(l["line_supply"] for l in out)
    tax = supply * 10 // 100
    return {"supply": supply, "tax": tax, "total": supply + tax, "lines": out}


def next_no(issued):
    prefix = "INV-" + issued.replace("-", "") + "-"
    rows = db.execute("SELECT invoice_no FROM tx_invoices WHERE invoice_no LIKE ?", (prefix + "%",)).fetchall()
    last = 0
    for r in rows:
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", r["invoice_no"])
        if m:
            last = max(last, int(m.group(1)))
    return f"{prefix}{last + 1:03d}"


def invoice_dict(row, with_lines=True):
    cust = db.execute("SELECT name FROM tx_customers WHERE biz_no=?", (row["biz_no"],)).fetchone()
    d = {k: row[k] for k in row.keys()}
    d["customer"] = cust["name"] if cust else ""
    if with_lines:
        d["lines"] = [
            {"line": r["line"], "item": r["item"], "qty": r["qty"], "unit_price": r["unit_price"],
             "line_supply": r["qty"] * r["unit_price"]}
            for r in db.execute("SELECT * FROM tx_lines WHERE invoice_no=? ORDER BY line", (row["invoice_no"],))
        ]
    return d


def insert_invoice(issued, biz_no, lines, amends=None):
    calc = compute(lines)
    no = next_no(issued)
    db.execute(
        "INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)",
        (no, issued, biz_no, calc["supply"], calc["tax"], calc["total"], "발행", amends, None),
    )
    for i, ln in enumerate(lines, 1):
        db.execute("INSERT INTO tx_lines VALUES (?,?,?,?,?)", (no, i, ln["item"], ln["qty"], ln["unit_price"]))
    return no


def get_row(no):
    return db.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/customers")
def customers():
    with LOCK:
        return [dict(r) for r in db.execute("SELECT biz_no,name,ceo FROM tx_customers ORDER BY biz_no")]


def parse_new(data):
    if customer_of(data.get("biz_no")) is None:
        raise bad("거래처")
    return parse_common(data)


@app.post("/api/invoices/preview")
async def preview(request: Request):
    data = await body_of(request)
    with LOCK:
        _, lines = parse_new(data)
        return compute(lines)


@app.post("/api/invoices")
async def create(request: Request):
    data = await body_of(request)
    with LOCK:
        issued, lines = parse_new(data)
        no = insert_invoice(issued, data["biz_no"], lines)
        db.commit()
        return JSONResponse(invoice_dict(get_row(no)), status_code=201)


@app.get("/api/invoices")
def list_invoices(month: str = ""):
    if not month:
        month = date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise bad("월")
    with LOCK:
        rows = db.execute(
            "SELECT * FROM tx_invoices WHERE issued LIKE ? ORDER BY invoice_no", (month + "-%",)
        ).fetchall()
        ok = [r for r in rows if r["status"] == "발행"]
        totals = {k: sum(r[k] for r in ok) for k in ("supply", "tax", "total")}
        return {"month": month, "count": len(rows), "totals": totals,
                "items": [invoice_dict(r, False) for r in rows]}


@app.get("/api/invoices/{no}")
def get_invoice(no: str):
    with LOCK:
        row = get_row(no)
        if row is None:
            raise ApiError(404, "계산서를 찾을 수 없습니다")
        return invoice_dict(row)


@app.post("/api/invoices/{no}/amend")
async def amend(no: str, request: Request):
    data = await body_of(request)
    with LOCK:
        issued, lines = parse_common(data)  # 400 먼저 (R7)
        row = get_row(no)
        if row is None:
            raise ApiError(404, "계산서를 찾을 수 없습니다")
        if row["status"] != "발행":
            raise ApiError(409, NOT_ISSUED)
        new_no = insert_invoice(issued, row["biz_no"], lines, amends=no)
        db.execute("UPDATE tx_invoices SET status='수정됨', amended_by=? WHERE invoice_no=?", (new_no, no))
        db.commit()
        return JSONResponse(invoice_dict(get_row(new_no)), status_code=201)


@app.post("/api/invoices/{no}/cancel")
def cancel(no: str):
    with LOCK:
        row = get_row(no)
        if row is None:
            raise ApiError(404, "계산서를 찾을 수 없습니다")
        if row["status"] != "발행":
            raise ApiError(409, NOT_ISSUED)
        db.execute("UPDATE tx_invoices SET status='취소' WHERE invoice_no=?", (no,))
        db.commit()
        return invoice_dict(get_row(no))
