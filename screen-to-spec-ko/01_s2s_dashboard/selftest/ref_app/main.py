# -*- coding: utf-8 -*-
"""채점기 자가 시험용 정답 앱 — PRD R1~R6 을 그대로 구현. tests/test_dod.py 가 9/9 여야 채점기가 맞다."""
import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DB = os.path.join(HERE, "dash.db")
app = FastAPI()


def load():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE dash_orders(order_id TEXT, ordered_at TEXT, customer TEXT, amount INTEGER, status TEXT);
    CREATE TABLE dash_stock(sku TEXT, name TEXT, qty INTEGER, safety_qty INTEGER);
    CREATE TABLE dash_inquiries(inquiry_id TEXT, received_at TEXT, channel TEXT, status TEXT);""")
    for name, table, n in (("orders.csv", "dash_orders", 5), ("stock.csv", "dash_stock", 4), ("inquiries.csv", "dash_inquiries", 4)):
        p = os.path.join(SEED, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
            con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * n)), rows)
    con.commit()
    con.close()


load()


def con():
    return sqlite3.connect(DB)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/summary")
def summary():
    today = dt.date.today()
    CON = con()
    n_rows = sum(CON.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("dash_orders", "dash_stock", "dash_inquiries"))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if n_rows == 0:
        return JSONResponse({"today_orders": None, "stock_alerts": None, "open_inquiries": None,
                             "daily_orders": [], "updated_at": now, "empty": True})
    today_orders = CON.execute("SELECT COUNT(*) FROM dash_orders WHERE substr(ordered_at,1,10)=? AND status<>'취소'",
                               (today.isoformat(),)).fetchone()[0]
    stock_alerts = CON.execute("SELECT COUNT(*) FROM dash_stock WHERE qty < safety_qty").fetchone()[0]
    open_inq = CON.execute("SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')").fetchone()[0]
    daily = []
    for i in range(6, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        c = CON.execute("SELECT COUNT(*) FROM dash_orders WHERE substr(ordered_at,1,10)=? AND status<>'취소'", (d,)).fetchone()[0]
        daily.append({"date": d, "count": c})
    return {"today_orders": today_orders, "stock_alerts": stock_alerts, "open_inquiries": open_inq,
            "daily_orders": daily, "updated_at": now, "empty": False}
