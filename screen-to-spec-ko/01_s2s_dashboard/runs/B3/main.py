import csv
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "dash.db"

TABLES = {
    "orders": ("dash_orders", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "stock": ("dash_stock", ["sku", "name", "qty", "safety_qty"]),
    "inquiries": ("dash_inquiries", ["inquiry_id", "received_at", "channel", "status"]),
}


def _read_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def init_db():
    """시작할 때마다 seed/ CSV 로 dash.db 를 새로 만든다."""
    seed = Path(os.environ.get("SEED_DIR", BASE / "seed"))
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    for name, (table, cols) in TABLES.items():
        con.execute(f"CREATE TABLE {table} ({', '.join(cols)})")
        rows = _read_csv(seed / f"{name}.csv")
        con.executemany(
            f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})",
            [[(r.get(c) or "").strip() for c in cols] for r in rows],
        )
    con.commit()
    con.close()


init_db()
app = FastAPI()


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


@app.get("/api/summary")
def summary():
    today = datetime.now().date()
    con = sqlite3.connect(DB_PATH)
    orders = con.execute("SELECT ordered_at, status FROM dash_orders").fetchall()
    stock = con.execute("SELECT qty, safety_qty FROM dash_stock").fetchall()
    inquiries = con.execute("SELECT status FROM dash_inquiries").fetchall()
    con.close()

    empty = not (orders or stock or inquiries)
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    counts = {d.isoformat(): 0 for d in days}
    for ordered_at, status in orders:
        if status == "취소":
            continue
        d = ordered_at[:10]
        if d in counts:
            counts[d] += 1

    return {
        "today_orders": counts[today.isoformat()],
        "stock_alerts": sum(1 for q, s in stock if _int(q) < _int(s)),
        "open_inquiries": sum(1 for (s,) in inquiries if s in ("접수", "처리중")),
        "daily_orders": [{"date": d.isoformat(), "count": counts[d.isoformat()]} for d in days],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "empty": empty,
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-store"})
