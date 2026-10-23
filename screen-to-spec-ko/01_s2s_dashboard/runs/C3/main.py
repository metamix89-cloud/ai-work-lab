import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "dash.db")
SEED = os.path.join(ROOT, "seed")

TABLES = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def rebuild_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    try:
        for table, (fname, cols) in TABLES.items():
            con.execute("CREATE TABLE %s (%s)" % (table, ", ".join(cols)))
            path = os.path.join(SEED, fname)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = [[(r.get(c) or "").strip() for c in cols] for r in csv.DictReader(f)]
            con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))), rows)
        con.commit()
    finally:
        con.close()


rebuild_db()
app = FastAPI()


@app.get("/api/summary")
def summary():
    today = dt.date.today()
    days = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]
    con = sqlite3.connect(DB)
    try:
        n_orders = con.execute("SELECT COUNT(*) FROM dash_orders").fetchone()[0]
        n_stock = con.execute("SELECT COUNT(*) FROM dash_stock").fetchone()[0]
        n_inq = con.execute("SELECT COUNT(*) FROM dash_inquiries").fetchone()[0]
        # R1/R4: 취소 제외, 날짜별 주문 수
        per_day = dict(con.execute(
            "SELECT substr(ordered_at,1,10), COUNT(*) FROM dash_orders WHERE status <> '취소' GROUP BY 1"))
        # R2: 같으면 경고 아님
        alerts = con.execute(
            "SELECT COUNT(*) FROM dash_stock WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)").fetchone()[0]
        # R3
        open_inq = con.execute(
            "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')").fetchone()[0]
    finally:
        con.close()
    empty = n_orders == 0 and n_stock == 0 and n_inq == 0  # R5
    daily = [{"date": d.isoformat(), "count": per_day.get(d.isoformat(), 0)} for d in days]
    body = {
        "today_orders": None if empty else daily[-1]["count"],
        "stock_alerts": None if empty else alerts,
        "open_inquiries": None if empty else open_inq,
        "daily_orders": daily,
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),  # R6
        "empty": empty,
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"), headers={"Cache-Control": "no-store"})
