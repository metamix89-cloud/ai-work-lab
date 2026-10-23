import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "dash.db")

TABLES = {
    "orders": ("dash_orders", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "stock": ("dash_stock", ["sku", "name", "qty", "safety_qty"]),
    "inquiries": ("dash_inquiries", ["inquiry_id", "received_at", "channel", "status"]),
}


def build_db():
    """시작할 때마다 기존 DB 를 지우고 seed/*.csv 로 새로 만든다."""
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    for name, (table, cols) in TABLES.items():
        con.execute("CREATE TABLE %s (%s)" % (table, ", ".join(cols)))
        path = os.path.join(BASE, "seed", name + ".csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [[(r.get(c) or "").strip() for c in cols] for r in csv.DictReader(f)]
        con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))), rows)
    con.commit()
    con.close()


build_db()
app = FastAPI()


@app.get("/api/summary")
def summary():
    con = sqlite3.connect(DB)
    n_all = sum(con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t, _ in TABLES.values())
    today = dt.date.today()
    daily = []
    for i in range(6, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        c = con.execute(
            "SELECT COUNT(*) FROM dash_orders WHERE substr(ordered_at,1,10)=? AND status<>'취소'",
            (d,)).fetchone()[0]
        daily.append({"date": d, "count": c})
    stock_alerts = con.execute(
        "SELECT COUNT(*) FROM dash_stock WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)").fetchone()[0]
    open_inq = con.execute(
        "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')").fetchone()[0]
    con.close()
    return JSONResponse(
        {"today_orders": daily[-1]["count"], "stock_alerts": stock_alerts, "open_inquiries": open_inq,
         "daily_orders": daily,
         "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
         "empty": n_all == 0},
        headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"),
                        headers={"Cache-Control": "no-store"})
