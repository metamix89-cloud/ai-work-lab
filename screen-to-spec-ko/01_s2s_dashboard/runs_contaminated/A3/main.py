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
NO_STORE = {"Cache-Control": "no-store"}


def read_csv(name):
    path = os.path.join(SEED, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_db():
    """시작할 때마다 기존 DB 를 지우고 seed/*.csv 로 새로 만든다."""
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    try:
        for table, (fname, cols) in TABLES.items():
            con.execute("CREATE TABLE %s (%s)" % (table, ", ".join(cols)))
            rows = read_csv(fname)
            con.executemany(
                "INSERT INTO %s VALUES (%s)" % (table, ", ".join("?" * len(cols))),
                [tuple((r.get(c) or "").strip() for c in cols) for r in rows],
            )
        con.commit()
    finally:
        con.close()


build_db()
app = FastAPI()


def summarize():
    today = dt.date.today()
    days = [(today - dt.timedelta(days=n)).isoformat() for n in range(6, -1, -1)]
    con = sqlite3.connect(DB)
    try:
        def one(sql, *args):
            return con.execute(sql, args).fetchone()[0]

        total = sum(one("SELECT COUNT(*) FROM " + t) for t in TABLES)
        per_day = dict(con.execute(
            "SELECT substr(ordered_at, 1, 10), COUNT(*) FROM dash_orders "
            "WHERE status <> '취소' AND substr(ordered_at, 1, 10) BETWEEN ? AND ? GROUP BY 1",
            (days[0], days[-1]),
        ).fetchall())
        data = {
            "today_orders": one("SELECT COUNT(*) FROM dash_orders WHERE status <> '취소' "
                                "AND substr(ordered_at, 1, 10) = ?", days[-1]),
            "stock_alerts": one("SELECT COUNT(*) FROM dash_stock "
                                "WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)"),
            "open_inquiries": one("SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수', '처리중')"),
            "daily_orders": [{"date": d, "count": per_day.get(d, 0)} for d in days],
        }
    finally:
        con.close()
    empty = total == 0
    if empty:  # 0 과 구분: 숫자는 null
        data.update(today_orders=None, stock_alerts=None, open_inquiries=None)
    data["updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    data["empty"] = empty
    return data


@app.get("/api/summary")
def api_summary():
    return JSONResponse(summarize(), headers=NO_STORE)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), headers=NO_STORE)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
