import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

BASE = Path(__file__).parent
SEED = BASE / "seed"
DB = BASE / "dash.db"

TABLES = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def load_db():
    """시작할 때마다 기존 DB 를 지우고 CSV 로 새로 만든다."""
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    for table, (fname, cols) in TABLES.items():
        con.execute(f"CREATE TABLE {table} ({', '.join(c + ' TEXT' for c in cols)})")
        path = SEED / fname
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [[(r.get(c) or "").strip() for c in cols] for r in csv.DictReader(f)]
        rows = [r for r in rows if any(r)]
        con.executemany(
            f"INSERT INTO {table} VALUES ({','.join('?' * len(cols))})", rows
        )
    con.commit()
    con.close()


load_db()
app = FastAPI()


@app.get("/api/summary")
def summary():
    today = datetime.now().date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    con = sqlite3.connect(DB)
    total = sum(
        con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES
    )

    counts = {d: 0 for d in days}
    for d, c in con.execute(
        "SELECT substr(ordered_at,1,10), COUNT(*) FROM dash_orders "
        "WHERE status != '취소' GROUP BY 1"
    ):
        if d in counts:
            counts[d] = c
    stock_alerts = con.execute(
        "SELECT COUNT(*) FROM dash_stock "
        "WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)"
    ).fetchone()[0]
    open_inq = con.execute(
        "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')"
    ).fetchone()[0]
    con.close()

    return {
        "today_orders": counts[days[-1]],
        "stock_alerts": stock_alerts,
        "open_inquiries": open_inq,
        "daily_orders": [{"date": d, "count": counts[d]} for d in days],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "empty": total == 0,
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-store"})
