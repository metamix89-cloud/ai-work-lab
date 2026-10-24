# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R7 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import datetime as dt
import os
import re
import sqlite3
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "invoice.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE tx_customers(biz_no TEXT PRIMARY KEY, name TEXT, ceo TEXT);
    CREATE TABLE tx_invoices(invoice_no TEXT PRIMARY KEY, issued TEXT, biz_no TEXT, supply INTEGER, tax INTEGER, total INTEGER, status TEXT, amends TEXT, amended_by TEXT);
    CREATE TABLE tx_lines(invoice_no TEXT, line INTEGER, item TEXT, qty INTEGER, unit_price INTEGER);""")
    for name, table, n in (("customers.csv", "tx_customers", 3), ("invoices.csv", "tx_invoices", 9), ("invoice_lines.csv", "tx_lines", 5)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
            con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), rows)
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def bad(msg="필수 항목을 확인하세요"):
    raise HTTPException(400, msg)


def is_int(v, lo):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo


def check_lines(lines):
    if not isinstance(lines, list) or not lines:
        bad("필수 항목을 확인하세요 — 품목 1줄 이상")
    out = []
    for ln in lines:
        if not isinstance(ln, dict) or not str(ln.get("item", "")).strip() or not is_int(ln.get("qty"), 1) or not is_int(ln.get("unit_price"), 0):
            bad("필수 항목을 확인하세요 — 품목명 · 수량(1 이상 정수) · 단가(0 이상 정수)")
        out.append({"item": str(ln["item"]).strip(), "qty": ln["qty"], "unit_price": ln["unit_price"], "line_supply": ln["qty"] * ln["unit_price"]})
    return out


def check_date(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        bad("필수 항목을 확인하세요 — 작성일 YYYY-MM-DD")
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        bad("필수 항목을 확인하세요 — 작성일 YYYY-MM-DD")
    return s


def money(lines):
    supply = sum(l["line_supply"] for l in lines)
    tax = supply * 10 // 100
    return supply, tax, supply + tax


def full(c, no):
    r = c.execute("""SELECT i.*, c.name AS customer FROM tx_invoices i LEFT JOIN tx_customers c ON c.biz_no=i.biz_no WHERE invoice_no=?""", (no,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["lines"] = [{"item": l["item"], "qty": l["qty"], "unit_price": l["unit_price"], "line_supply": l["qty"] * l["unit_price"]}
                  for l in c.execute("SELECT * FROM tx_lines WHERE invoice_no=? ORDER BY line", (no,))]
    return d


def next_no(c, issued):
    prefix = "INV-%s-" % issued.replace("-", "")
    nums = [int(r["invoice_no"][-3:]) for r in c.execute("SELECT invoice_no FROM tx_invoices WHERE invoice_no LIKE ?", (prefix + "%",))]
    return prefix + "%03d" % (max(nums + [0]) + 1)


def save(c, issued, biz, lines, amends=""):
    no = next_no(c, issued)
    s, t, tot = money(lines)
    c.execute("INSERT INTO tx_invoices VALUES (?,?,?,?,?,?,'발행',?, '')", (no, issued, biz, s, t, tot, amends))
    c.executemany("INSERT INTO tx_lines VALUES (?,?,?,?,?)", [(no, i + 1, l["item"], l["qty"], l["unit_price"]) for i, l in enumerate(lines)])
    return no


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/customers")
def customers():
    return [dict(r) for r in con().execute("SELECT * FROM tx_customers")]


def parse_new(c, body):
    biz = body.get("biz_no")
    if not c.execute("SELECT 1 FROM tx_customers WHERE biz_no=?", (biz,)).fetchone():
        bad("필수 항목을 확인하세요 — 등록된 거래처")
    return biz, check_date(body.get("issued")), check_lines(body.get("lines"))


@app.post("/api/invoices/preview")
def preview(body: dict[str, Any] = Body(...)):
    _, _, lines = parse_new(con(), body)
    s, t, tot = money(lines)
    return {"supply": s, "tax": t, "total": tot, "lines": lines}


@app.post("/api/invoices", status_code=201)
def create(body: dict[str, Any] = Body(...)):
    c = con()
    biz, issued, lines = parse_new(c, body)
    no = save(c, issued, biz, lines)
    c.commit()
    return full(c, no)


@app.get("/api/invoices")
def ledger(month: str = ""):
    month = month or dt.date.today().strftime("%Y-%m")
    c = con()
    items = []
    for r in c.execute("SELECT invoice_no FROM tx_invoices WHERE issued LIKE ? ORDER BY invoice_no", (month + "-%",)):
        d = full(c, r["invoice_no"])
        d.pop("lines")
        items.append(d)
    live = [i for i in items if i["status"] == "발행"]
    return {"month": month, "count": len(items), "totals": {k: sum(i[k] for i in live) for k in ("supply", "tax", "total")}, "items": items}


@app.get("/api/invoices/{no}")
def detail(no: str):
    d = full(con(), no)
    if not d:
        raise HTTPException(404, "계산서가 없습니다")
    return d


@app.post("/api/invoices/{no}/amend", status_code=201)
def amend(no: str, body: dict[str, Any] = Body(...)):
    c = con()
    issued, lines = check_date(body.get("issued")), check_lines(body.get("lines"))      # 400 먼저
    orig = full(c, no)
    if not orig:
        raise HTTPException(404, "계산서가 없습니다")
    if orig["status"] != "발행":
        raise HTTPException(409, "발행 상태가 아닙니다")
    new = save(c, issued, orig["biz_no"], lines, amends=no)
    c.execute("UPDATE tx_invoices SET status='수정됨', amended_by=? WHERE invoice_no=?", (new, no))
    c.commit()
    return full(c, new)


@app.post("/api/invoices/{no}/cancel")
def cancel(no: str):
    c = con()
    orig = full(c, no)
    if not orig:
        raise HTTPException(404, "계산서가 없습니다")
    if orig["status"] != "발행":
        raise HTTPException(409, "발행 상태가 아닙니다")
    c.execute("UPDATE tx_invoices SET status='취소' WHERE invoice_no=?", (no,))
    c.commit()
    return full(c, no)
