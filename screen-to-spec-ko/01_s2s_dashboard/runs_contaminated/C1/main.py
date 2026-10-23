import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB = os.path.join(BASE, "dash.db")

TABLES = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def load_db():
    """시작할 때마다 기존 DB 를 지우고 seed CSV 로 새로 만든다."""
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    for table, (fname, cols) in TABLES.items():
        con.execute("CREATE TABLE %s (%s)" % (table, ", ".join(cols)))
        path = os.path.join(SEED, fname)
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    if any((r.get(c) or "").strip() for c in cols):
                        rows.append([(r.get(c) or "").strip() for c in cols])
        con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))), rows)
    con.commit()
    con.close()


load_db()
app = FastAPI()


@app.get("/api/summary")
def summary():
    today = dt.date.today()
    con = sqlite3.connect(DB)

    def one(sql, *a):
        return con.execute(sql, a).fetchone()[0]

    total = sum(one("SELECT COUNT(*) FROM %s" % t) for t in TABLES)
    empty = total == 0  # R5
    count_day = "SELECT COUNT(*) FROM dash_orders WHERE substr(ordered_at,1,10)=? AND status<>'취소'"
    today_orders = one(count_day, today.isoformat())  # R1
    stock_alerts = one("SELECT COUNT(*) FROM dash_stock WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)")  # R2
    open_inq = one("SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')")  # R3
    daily = []  # R4
    for i in range(6, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        daily.append({"date": d, "count": one(count_day, d)})
    con.close()
    return JSONResponse(
        {"today_orders": today_orders, "stock_alerts": stock_alerts, "open_inquiries": open_inq,
         "daily_orders": daily, "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),  # R6
         "empty": empty},
        headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), headers={"Cache-Control": "no-store"})
