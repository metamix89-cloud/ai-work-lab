import csv
import datetime as dt
import os
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB = os.path.join(BASE, "dash.db")

SCHEMA = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def load_db():
    """시작할 때마다 DB 를 지우고 seed/*.csv 로 새로 만든다."""
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    for table, (fname, cols) in SCHEMA.items():
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


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def summarize():
    today = dt.date.today()
    days = [today - dt.timedelta(days=n) for n in range(6, -1, -1)]  # 6일 전 → 오늘
    con = sqlite3.connect(DB)
    try:
        empty = all(one(con, "SELECT COUNT(*) FROM " + t) == 0 for t in SCHEMA)
        # R1·R4: 취소 제외, 날짜별 주문 수 (주문 없는 날도 0 으로 칸을 둔다)
        per_day = dict(con.execute(
            "SELECT substr(ordered_at,1,10), COUNT(*) FROM dash_orders "
            "WHERE status <> '취소' GROUP BY 1").fetchall())
        daily = [{"date": d.isoformat(), "count": per_day.get(d.isoformat(), 0)} for d in days]
        return {
            "today_orders": per_day.get(today.isoformat(), 0),
            # R2: 같으면 경고 아님
            "stock_alerts": one(con, "SELECT COUNT(*) FROM dash_stock "
                                     "WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)"),
            # R3: 접수 · 처리중
            "open_inquiries": one(con, "SELECT COUNT(*) FROM dash_inquiries "
                                       "WHERE status IN ('접수','처리중')"),
            "daily_orders": daily,
            "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "empty": empty,
        }
    finally:
        con.close()


@app.get("/api/summary")
def api_summary():
    return JSONResponse(summarize(), headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"),
                        headers={"Cache-Control": "no-store"})
