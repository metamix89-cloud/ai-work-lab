import csv
import os
import sqlite3
from contextlib import asynccontextmanager
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


def read_csv(name):
    path = SEED / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def rebuild_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(DB) + suffix)
        if p.exists():
            p.unlink()
    con = sqlite3.connect(DB)
    for table, (fname, cols) in TABLES.items():
        con.execute(f"CREATE TABLE {table} ({', '.join(c + ' TEXT' for c in cols)})")
        rows = [[(r.get(c) or "").strip() for c in cols] for r in read_csv(fname)]
        con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})", rows)
    con.commit()
    con.close()


@asynccontextmanager
async def lifespan(app):
    rebuild_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/summary")
def summary():
    today = datetime.now().date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    con = sqlite3.connect(DB)
    total = sum(
        con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES
    )
    empty = total == 0

    # R1, R4: 취소 제외, 날짜별 주문 수
    counts = dict(
        con.execute(
            "SELECT substr(ordered_at, 1, 10), COUNT(*) FROM dash_orders "
            "WHERE status <> '취소' GROUP BY 1"
        ).fetchall()
    )
    # R2: 같으면 경고가 아니다
    stock_alerts = con.execute(
        "SELECT COUNT(*) FROM dash_stock "
        "WHERE CAST(qty AS INTEGER) < CAST(safety_qty AS INTEGER)"
    ).fetchone()[0]
    # R3
    open_inq = con.execute(
        "SELECT COUNT(*) FROM dash_inquiries WHERE status IN ('접수', '처리중')"
    ).fetchone()[0]
    con.close()

    return {
        "today_orders": None if empty else counts.get(days[-1], 0),
        "stock_alerts": None if empty else stock_alerts,
        "open_inquiries": None if empty else open_inq,
        "daily_orders": [{"date": d, "count": counts.get(d, 0)} for d in days],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "empty": empty,
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
