import csv
import datetime as dt
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(ROOT, "seed")
DB = os.path.join(ROOT, "dash.db")

TABLES = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def build_db():
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


@asynccontextmanager
async def lifespan(_):
    build_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/summary")
def summary():
    today = dt.date.today()
    days = [(today - dt.timedelta(days=n)).isoformat() for n in range(6, -1, -1)]
    con = sqlite3.connect(DB)
    try:
        n_rows = sum(con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in TABLES)
        counts = {d: 0 for d in days}
        for day, n in con.execute(
            "SELECT substr(ordered_at,1,10), COUNT(*) FROM dash_orders "
            "WHERE status <> '취소' GROUP BY 1"
        ):
            if day in counts:
                counts[day] = n
        stock = con.execute(
            "SELECT COUNT(*) FROM dash_stock WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)"
        ).fetchone()[0]
        inq = con.execute(
            "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')"
        ).fetchone()[0]
    finally:
        con.close()
    empty = n_rows == 0
    body = {
        "today_orders": None if empty else counts[days[-1]],
        "stock_alerts": None if empty else stock,
        "open_inquiries": None if empty else inq,
        "daily_orders": [{"date": d, "count": counts[d]} for d in days],
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "empty": empty,
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"), headers={"Cache-Control": "no-store"})
