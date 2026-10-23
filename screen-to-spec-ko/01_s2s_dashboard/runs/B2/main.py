import csv
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

BASE = Path(__file__).resolve().parent
SEED_DIR = Path(os.environ.get("SEED_DIR", BASE / "seed"))
DB_PATH = Path(os.environ.get("DB_PATH", BASE / "dash.db"))

TABLES = {
    "dash_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "dash_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "dash_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}


def read_csv(name, cols):
    path = SEED_DIR / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [[(row.get(c) or "").strip() for c in cols] for row in csv.DictReader(f)]


def rebuild_db():
    for p in (DB_PATH, Path(str(DB_PATH) + "-journal")):
        if p.exists():
            p.unlink()
    con = sqlite3.connect(DB_PATH)
    for table, (fname, cols) in TABLES.items():
        con.execute(f"CREATE TABLE {table} ({', '.join(c + ' TEXT' for c in cols)})")
        rows = read_csv(fname, cols)
        con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})", rows)
    con.commit()
    con.close()


rebuild_db()
app = FastAPI()


@app.get("/api/summary")
def summary():
    today = datetime.now().date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    con = sqlite3.connect(DB_PATH)
    try:
        n_orders = con.execute("SELECT COUNT(*) FROM dash_orders").fetchone()[0]
        n_stock = con.execute("SELECT COUNT(*) FROM dash_stock").fetchone()[0]
        n_inq = con.execute("SELECT COUNT(*) FROM dash_inquiries").fetchone()[0]
        counts = {d.isoformat(): 0 for d in days}
        for (ordered_at,) in con.execute(
            "SELECT ordered_at FROM dash_orders WHERE status != '취소'"
        ):
            key = ordered_at[:10]
            if key in counts:
                counts[key] += 1
        alerts = 0
        for qty, safety in con.execute("SELECT qty, safety_qty FROM dash_stock"):
            try:
                if float(qty) < float(safety):
                    alerts += 1
            except ValueError:
                pass
        open_inq = con.execute(
            "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수','처리중')"
        ).fetchone()[0]
    finally:
        con.close()
    empty = n_orders == 0 and n_stock == 0 and n_inq == 0
    return {
        "today_orders": None if empty else counts[today.isoformat()],
        "stock_alerts": None if empty else alerts,
        "open_inquiries": None if empty else open_inq,
        "daily_orders": [{"date": d, "count": c} for d, c in counts.items()],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "empty": empty,
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-store"})
