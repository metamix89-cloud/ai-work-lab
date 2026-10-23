import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "dash.db")

TABLES = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def rebuild_db():
    """시작할 때마다 기존 DB 를 지우고 seed/*.csv 로 새로 만든다."""
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    con = sqlite3.connect(DB)
    for table, (fname, cols) in TABLES.items():
        con.execute("CREATE TABLE %s (%s)" % (table, ", ".join(cols)))
        path = os.path.join(BASE, "seed", fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [[(r.get(c) or "").strip() for c in cols] for r in csv.DictReader(f)]
        rows = [r for r in rows if any(r)]
        con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))), rows)
    con.commit()
    con.close()


rebuild_db()
app = FastAPI()


@app.get("/api/summary")
def summary():
    today = dt.date.today()
    days = [(today - dt.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    con = sqlite3.connect(DB)
    try:
        total = sum(con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in TABLES)
        counts = dict(con.execute(
            "SELECT substr(ordered_at,1,10), COUNT(*) FROM dash_orders "
            "WHERE status != '취소' GROUP BY 1").fetchall())
        stock_alerts = con.execute(
            "SELECT COUNT(*) FROM dash_stock "
            "WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)").fetchone()[0]
        open_inq = con.execute(
            "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')").fetchone()[0]
    finally:
        con.close()
    body = {
        "today_orders": counts.get(days[-1], 0),
        "stock_alerts": stock_alerts,
        "open_inquiries": open_inq,
        "daily_orders": [{"date": d, "count": counts.get(d, 0)} for d in days],
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "empty": total == 0,
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"),
                        headers={"Cache-Control": "no-store"})
