import csv
import os
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "invoice.db"
SEED = BASE / "seed"
LOCK = threading.RLock()

app = FastAPI()


class ApiError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


@app.exception_handler(ApiError)
async def api_error_handler(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status)


def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def read_csv(name):
    with open(SEED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    con = connect()
    con.executescript(
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
        con.execute("INSERT INTO tx_customers VALUES (?,?,?)", (r["biz_no"], r["name"], r["ceo"]))
    for r in read_csv("invoices.csv"):
        con.execute(
            "INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)",
            (r["invoice_no"], r["issued"], r["biz_no"], int(r["supply"]), int(r["tax"]),
             int(r["total"]), r["status"], r["amends"] or None, r["amended_by"] or None),
        )
    for r in read_csv("invoice_lines.csv"):
        con.execute(
            "INSERT INTO tx_lines VALUES (?,?,?,?,?)",
            (r["invoice_no"], int(r["line"]), r["item"], int(r["qty"]), int(r["unit_price"])),
        )
    con.commit()
    con.close()


init_db()

BAD = "필수 항목을 확인하세요"


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def parse_date(v):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return None
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        return None
    return v


def validate_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise ApiError(400, f"{BAD}: 품목 줄")
    out = []
    for i, ln in enumerate(lines, 1):
        if not isinstance(ln, dict):
            raise ApiError(400, f"{BAD}: {i}번째 줄")
        item, qty, price = ln.get("item"), ln.get("qty"), ln.get("unit_price")
        if not isinstance(item, str) or not item.strip():
            raise ApiError(400, f"{BAD}: {i}번째 줄 품목명")
        if not is_int(qty) or qty < 1:
            raise ApiError(400, f"{BAD}: {i}번째 줄 수량")
        if not is_int(price) or price < 0:
            raise ApiError(400, f"{BAD}: {i}번째 줄 단가")
        out.append({"item": item.strip(), "qty": qty, "unit_price": price, "line_supply": qty * price})
    return out


def compute(lines):
    supply = sum(l["line_supply"] for l in lines)
    tax = supply * 10 // 100
    return supply, tax, supply + tax


async def body_of(request):
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, BAD)
    if not isinstance(body, dict):
        raise ApiError(400, BAD)
    return body


def validate_issue(body, con, need_customer=True):
    issued = parse_date(body.get("issued"))
    if not issued:
        raise ApiError(400, f"{BAD}: 작성일")
    biz_no = body.get("biz_no")
    if need_customer:
        if not isinstance(biz_no, str) or not con.execute(
                "SELECT 1 FROM tx_customers WHERE biz_no=?", (biz_no,)).fetchone():
            raise ApiError(400, f"{BAD}: 거래처")
    return issued, biz_no, validate_lines(body.get("lines"))


def next_no(con, issued):
    prefix = "INV-" + issued.replace("-", "") + "-"
    n = 0
    for (no,) in con.execute("SELECT invoice_no FROM tx_invoices WHERE invoice_no LIKE ?", (prefix + "%",)):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", no)
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1:03d}"


def invoice_dict(con, row, with_lines=True):
    d = dict(row)
    c = con.execute("SELECT name FROM tx_customers WHERE biz_no=?", (d["biz_no"],)).fetchone()
    d["customer"] = c["name"] if c else None
    if with_lines:
        d["lines"] = [
            {"line": r["line"], "item": r["item"], "qty": r["qty"], "unit_price": r["unit_price"],
             "line_supply": r["qty"] * r["unit_price"]}
            for r in con.execute("SELECT * FROM tx_lines WHERE invoice_no=? ORDER BY line", (d["invoice_no"],))
        ]
    return d


def insert_invoice(con, issued, biz_no, lines, amends=None):
    supply, tax, total = compute(lines)
    no = next_no(con, issued)
    con.execute("INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,?,?,?)",
                (no, issued, biz_no, supply, tax, total, "발행", amends, None))
    for i, l in enumerate(lines, 1):
        con.execute("INSERT INTO tx_lines VALUES (?,?,?,?,?)", (no, i, l["item"], l["qty"], l["unit_price"]))
    return no


def fetch(con, no):
    return invoice_dict(con, con.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone())


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/customers")
def customers():
    with LOCK:
        con = connect()
        try:
            return [dict(r) for r in con.execute("SELECT * FROM tx_customers ORDER BY biz_no")]
        finally:
            con.close()


@app.post("/api/invoices/preview")
async def preview(request: Request):
    body = await body_of(request)
    with LOCK:
        con = connect()
        try:
            _, _, lines = validate_issue(body, con)
        finally:
            con.close()
    supply, tax, total = compute(lines)
    return {"supply": supply, "tax": tax, "total": total, "lines": lines}


@app.post("/api/invoices", status_code=201)
async def create(request: Request):
    body = await body_of(request)
    with LOCK:
        con = connect()
        try:
            issued, biz_no, lines = validate_issue(body, con)
            no = insert_invoice(con, issued, biz_no, lines)
            con.commit()
            return fetch(con, no)
        finally:
            con.close()


@app.get("/api/invoices")
def list_invoices(month: str = None):
    if month is None:
        month = date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ApiError(400, "month 형식은 YYYY-MM 입니다")
    with LOCK:
        con = connect()
        try:
            rows = con.execute("SELECT * FROM tx_invoices WHERE issued LIKE ? ORDER BY invoice_no",
                               (month + "-%",)).fetchall()
            items = [invoice_dict(con, r, with_lines=False) for r in rows]
        finally:
            con.close()
    valid = [i for i in items if i["status"] == "발행"]
    return {"month": month, "count": len(items),
            "totals": {"supply": sum(i["supply"] for i in valid), "tax": sum(i["tax"] for i in valid),
                       "total": sum(i["total"] for i in valid)},
            "items": items}


@app.get("/api/invoices/{no}")
def get_invoice(no: str):
    with LOCK:
        con = connect()
        try:
            if not con.execute("SELECT 1 FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone():
                raise ApiError(404, "계산서를 찾을 수 없습니다")
            return fetch(con, no)
        finally:
            con.close()


@app.post("/api/invoices/{no}/amend", status_code=201)
async def amend(no: str, request: Request):
    body = await body_of(request)
    with LOCK:
        con = connect()
        try:
            issued, _, lines = validate_issue(body, con, need_customer=False)
            orig = con.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone()
            if not orig:
                raise ApiError(404, "계산서를 찾을 수 없습니다")
            if orig["status"] != "발행":
                raise ApiError(409, "발행 상태가 아닙니다")
            new_no = insert_invoice(con, issued, orig["biz_no"], lines, amends=no)
            con.execute("UPDATE tx_invoices SET status='수정됨', amended_by=? WHERE invoice_no=?", (new_no, no))
            con.commit()
            return fetch(con, new_no)
        finally:
            con.close()


@app.post("/api/invoices/{no}/cancel")
def cancel(no: str):
    with LOCK:
        con = connect()
        try:
            row = con.execute("SELECT * FROM tx_invoices WHERE invoice_no=?", (no,)).fetchone()
            if not row:
                raise ApiError(404, "계산서를 찾을 수 없습니다")
            if row["status"] != "발행":
                raise ApiError(409, "발행 상태가 아닙니다")
            con.execute("UPDATE tx_invoices SET status='취소' WHERE invoice_no=?", (no,))
            con.commit()
            return fetch(con, no)
        finally:
            con.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
