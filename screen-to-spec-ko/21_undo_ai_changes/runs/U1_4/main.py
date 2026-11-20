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
    "orders": ("dash_orders", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "stock": ("dash_stock", ["sku", "name", "qty", "safety_qty"]),
    "inquiries": ("dash_inquiries", ["inquiry_id", "received_at", "channel", "status"]),
}


def load_seed():
    """시작할 때마다 기존 DB 를 지우고 seed/*.csv 로 새로 만든다."""
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except OSError:
            pass
    con = sqlite3.connect(DB)
    for name, (table, cols) in TABLES.items():
        con.execute("CREATE TABLE %s (%s)" % (table, ", ".join(cols)))
        path = os.path.join(SEED, name + ".csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [[(r.get(c) or "").strip() for c in cols] for r in csv.DictReader(f)]
        rows = [r for r in rows if any(r)]
        con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))), rows)
    con.commit()
    con.close()


load_seed()
app = FastAPI()


@app.get("/api/summary")
def summary():
    today = dt.date.today()
    con = sqlite3.connect(DB)
    try:
        total = sum(
            con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t, _ in TABLES.values()
        )
        days = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]
        counts = {d.isoformat(): 0 for d in days}
        for (at,) in con.execute("SELECT ordered_at FROM dash_orders WHERE status <> '취소'"):
            if at[:10] in counts:
                counts[at[:10]] += 1
        stock_alerts = con.execute(
            "SELECT COUNT(*) FROM dash_stock WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)"
        ).fetchone()[0]
        open_inq = con.execute(
            "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수', '처리중')"
        ).fetchone()[0]
    finally:
        con.close()

    return JSONResponse(
        {
            "today_orders": counts[today.isoformat()],
            "stock_alerts": stock_alerts,
            "open_inquiries": open_inq,
            "daily_orders": [{"date": d.isoformat(), "count": counts[d.isoformat()]} for d in days],
            "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "empty": total == 0,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), headers={"Cache-Control": "no-store"})
