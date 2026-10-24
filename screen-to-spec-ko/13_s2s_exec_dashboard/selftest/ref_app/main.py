# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R9 그대로. tests/test_dod.py 가 9/9 여야 채점기가 맞다.
기간은 날짜(앞 10자리)로 비교한다 — 'ordered_at <= 종료일' 을 문자열로 비교하면 종료일 주문이 빠진다."""
import csv
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "biz.db")
app = FastAPI()
VISIBLE = {"exec": {"orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries", "top"},
           "sales": {"orders", "revenue", "cancel_rate", "open_inquiries"},
           "logistics": {"orders", "stock_alerts"}}


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE biz_users(user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE biz_orders(order_id TEXT, ordered_at TEXT, customer TEXT, amount INTEGER, status TEXT);
    CREATE TABLE biz_stock(sku TEXT, name TEXT, qty INTEGER, safety_qty INTEGER);
    CREATE TABLE biz_inquiries(inquiry_id TEXT, received_at TEXT, channel TEXT, status TEXT);""")
    for name, table, n in (("users.csv", "biz_users", 3), ("orders.csv", "biz_orders", 5),
                           ("stock.csv", "biz_stock", 4), ("inquiries.csv", "biz_inquiries", 4)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), [r[:n] for r in list(csv.reader(f))[1:] if r])
    con.commit()
    con.close()


load()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def parse(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError
    return date.fromisoformat(s)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [dict(u) for u in con().execute("SELECT * FROM biz_users ORDER BY rowid")]


@app.get("/api/dashboard")
def dashboard(viewer: str | None = Query(default=None), frm: str | None = Query(default=None, alias="from"), to: str | None = None):
    if not viewer:
        raise HTTPException(400, "사용자를 확인하세요")
    try:
        if frm is None and to is None:
            t = date.today()
            f = t - timedelta(days=6)
        elif frm is None or to is None:
            raise ValueError
        else:
            f, t = parse(frm), parse(to)
        if f > t or (t - f).days + 1 > 31:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "기간을 확인하세요")
    c = con()
    u = c.execute("SELECT * FROM biz_users WHERE user_id=?", (viewer,)).fetchone()
    if not u:
        raise HTTPException(404, "사용자가 없습니다")
    see = VISIBLE.get(u["role"], set())
    fs, ts = f.isoformat(), t.isoformat()
    orders = [o for o in c.execute("SELECT * FROM biz_orders") if fs <= o["ordered_at"][:10] <= ts]
    live = [o for o in orders if o["status"] != "취소"]
    shipped = [o for o in orders if o["status"] == "출고"]
    cancel = sum(1 for o in orders if o["status"] == "취소")
    rate = float((Decimal(cancel * 100) / Decimal(len(orders))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if orders else None
    allm = {"orders": len(live), "revenue": sum(int(o["amount"]) for o in shipped), "cancel_rate": rate,
            "stock_alerts": sum(1 for s in c.execute("SELECT * FROM biz_stock") if int(s["qty"]) < int(s["safety_qty"])),
            "open_inquiries": sum(1 for i in c.execute("SELECT * FROM biz_inquiries")
                                  if fs <= i["received_at"][:10] <= ts and i["status"] in ("접수", "처리중"))}
    days = [(f + timedelta(days=k)).isoformat() for k in range((t - f).days + 1)]
    out = {"period": {"from": fs, "to": ts}, "metrics": {k: v for k, v in allm.items() if k in see},
           "daily": [{"date": d, "count": sum(1 for o in live if o["ordered_at"][:10] == d)} for d in days],
           "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if "top" in see:
        by = {}
        for o in shipped:
            by[o["customer"]] = by.get(o["customer"], 0) + int(o["amount"])
        out["top_customers"] = [{"customer": k, "revenue": v} for k, v in sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
    return out
