import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "dash.db")
SEED = os.path.join(BASE, "seed")

TABLES = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def load_db():
    """시작할 때마다 기존 DB 를 지우고 seed/*.csv 로 새로 만든다."""
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    for table, (fname, cols) in TABLES.items():
        con.execute("CREATE TABLE %s (%s)" % (table, ", ".join(cols)))
        path = os.path.join(SEED, fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [[(r.get(c) or "").strip() for c in cols] for r in csv.DictReader(f)]
        con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))), rows)
    con.commit()
    con.close()


load_db()
app = FastAPI()

COUNT_DAY = "SELECT COUNT(*) FROM dash_orders WHERE substr(ordered_at,1,10)=? AND status<>'취소'"


@app.get("/api/summary")
def summary():
    today = dt.date.today()
    con = sqlite3.connect(DB)
    try:
        n_orders = con.execute("SELECT COUNT(*) FROM dash_orders").fetchone()[0]
        n_stock = con.execute("SELECT COUNT(*) FROM dash_stock").fetchone()[0]
        n_inq = con.execute("SELECT COUNT(*) FROM dash_inquiries").fetchone()[0]
        stock_alerts = con.execute(
            "SELECT COUNT(*) FROM dash_stock WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)").fetchone()[0]
        open_inq = con.execute(
            "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')").fetchone()[0]
        daily = []
        for i in range(6, -1, -1):
            d = (today - dt.timedelta(days=i)).isoformat()
            daily.append({"date": d, "count": con.execute(COUNT_DAY, (d,)).fetchone()[0]})
    finally:
        con.close()
    body = {"today_orders": daily[-1]["count"], "stock_alerts": stock_alerts, "open_inquiries": open_inq,
            "daily_orders": daily, "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "empty": n_orders == 0 and n_stock == 0 and n_inq == 0}
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), headers={"Cache-Control": "no-store"})
