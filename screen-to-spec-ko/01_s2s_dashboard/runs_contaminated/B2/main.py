import csv
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB = BASE / "dash.db"

TABLES = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def read_rows(filename, cols):
    path = SEED / filename
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [[(row.get(c) or "").strip() for c in cols] for row in csv.DictReader(f)]


def rebuild_db():
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(str(DB) + suffix)
        except FileNotFoundError:
            pass
    con = sqlite3.connect(DB)
    for table, (filename, cols) in TABLES.items():
        con.execute(f"CREATE TABLE {table} ({', '.join(c + ' TEXT' for c in cols)})")
        con.executemany(
            f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})",
            read_rows(filename, cols),
        )
    con.commit()
    con.close()


rebuild_db()
app = FastAPI()


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


@app.get("/api/summary")
def summary():
    today = datetime.now().date()
    con = sqlite3.connect(DB)
    try:
        counts = [
            con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES
        ]
        empty = all(c == 0 for c in counts)  # R5

        # R1/R4: 취소 제외, 날짜별 주문 수
        per_day = {}
        for ordered_at, status in con.execute("SELECT ordered_at, status FROM dash_orders"):
            if status == "취소":
                continue
            d = ordered_at[:10]
            per_day[d] = per_day.get(d, 0) + 1
        days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        daily = [{"date": d, "count": per_day.get(d, 0)} for d in days]

        # R2: qty < safety_qty (같으면 경고 아님)
        alerts = sum(
            1
            for qty, safety in con.execute("SELECT qty, safety_qty FROM dash_stock")
            if to_int(qty) < to_int(safety)
        )
        # R3: 접수 · 처리중
        open_inq = con.execute(
            "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')"
        ).fetchone()[0]
    finally:
        con.close()

    return {
        "today_orders": per_day.get(days[-1], 0),
        "stock_alerts": alerts,
        "open_inquiries": open_inq,
        "daily_orders": daily,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),  # R6
        "empty": empty,
    }


@app.get("/")
def index():
    return FileResponse(
        BASE / "static" / "index.html", headers={"Cache-Control": "no-store"}
    )
