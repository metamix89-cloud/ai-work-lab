import csv
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).resolve().parent
SEED = BASE / "seed"
DB = BASE / "biz.db"

SCHEMA = {
    "biz_users": ("users.csv", ["user_id", "name", "role"], []),
    "biz_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"], ["amount"]),
    "biz_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"], ["qty", "safety_qty"]),
    "biz_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"], []),
}

VISIBLE = {
    "exec": ["orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries"],
    "sales": ["orders", "revenue", "cancel_rate", "open_inquiries"],
    "logistics": ["orders", "stock_alerts"],
}

MAX_DAYS = 31
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def build_db():
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(str(DB) + suffix)
        except FileNotFoundError:
            pass
    con = sqlite3.connect(DB)
    for table, (fname, cols, ints) in SCHEMA.items():
        defs = ", ".join(f"{c} {'INTEGER' if c in ints else 'TEXT'}" for c in cols)
        con.execute(f"CREATE TABLE {table} ({defs})")
        with open(SEED / fname, encoding="utf-8-sig", newline="") as f:
            rows = [
                [int(r[c]) if c in ints else r[c].strip() for c in cols]
                for r in csv.DictReader(f)
            ]
        marks = ", ".join("?" * len(cols))
        con.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
    con.commit()
    con.close()


build_db()

app = FastAPI()


def reject(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def parse_day(s):
    if not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/users")
def users():
    with conn() as con:
        rows = con.execute("SELECT user_id, name, role FROM biz_users ORDER BY rowid").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/dashboard")
def dashboard(viewer: str = Query(None), from_: str = Query(None, alias="from"), to: str = Query(None)):
    # R9: checks that need only the query come first (400), then lookups (404)
    if not viewer:
        return reject(400, "사용자를 확인하세요")
    from_ = from_ or None
    to = to or None
    if from_ is None and to is None:
        end = date.today()
        start = end - timedelta(days=6)
    elif from_ is None or to is None:
        return reject(400, "기간을 확인하세요")
    else:
        start, end = parse_day(from_), parse_day(to)
        if start is None or end is None or start > end or (end - start).days + 1 > MAX_DAYS:
            return reject(400, "기간을 확인하세요")

    with conn() as con:
        user = con.execute("SELECT role FROM biz_users WHERE user_id = ?", (viewer,)).fetchone()
        if user is None:
            return reject(404, "사용자를 찾을 수 없습니다")
        role = user["role"]
        s, e = start.isoformat(), end.isoformat()
        in_period = "substr(ordered_at, 1, 10) BETWEEN ? AND ?"

        total, canceled, valid, revenue = con.execute(
            f"""SELECT COUNT(*),
                       COALESCE(SUM(status = '취소'), 0),
                       COALESCE(SUM(status != '취소'), 0),
                       COALESCE(SUM(CASE WHEN status = '출고' THEN amount END), 0)
                FROM biz_orders WHERE {in_period}""",
            (s, e),
        ).fetchone()
        all_metrics = {
            "orders": valid,
            "revenue": revenue,
            "cancel_rate": round(canceled * 100 / total + 1e-9, 1) if total else None,
            "stock_alerts": con.execute(
                "SELECT COUNT(*) FROM biz_stock WHERE qty < safety_qty"
            ).fetchone()[0],
            "open_inquiries": con.execute(
                """SELECT COUNT(*) FROM biz_inquiries
                   WHERE substr(received_at, 1, 10) BETWEEN ? AND ? AND status IN ('접수', '처리중')""",
                (s, e),
            ).fetchone()[0],
        }
        per_day = dict(
            con.execute(
                f"""SELECT substr(ordered_at, 1, 10), COUNT(*) FROM biz_orders
                    WHERE {in_period} AND status != '취소' GROUP BY 1""",
                (s, e),
            ).fetchall()
        )
        daily = []
        d = start
        while d <= end:
            daily.append({"date": d.isoformat(), "count": per_day.get(d.isoformat(), 0)})
            d += timedelta(days=1)

        result = {
            "period": {"from": s, "to": e},
            "metrics": {k: all_metrics[k] for k in VISIBLE.get(role, [])},
            "daily": daily,
        }
        if role == "exec":
            result["top_customers"] = [
                {"customer": r["customer"], "revenue": r["revenue"]}
                for r in con.execute(
                    f"""SELECT customer, SUM(amount) AS revenue FROM biz_orders
                        WHERE {in_period} AND status = '출고'
                        GROUP BY customer ORDER BY revenue DESC, customer ASC LIMIT 5""",
                    (s, e),
                )
            ]
        result["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return result


if __name__ == "__main__":
    uvicorn.run(app, port=int(os.environ.get("PORT", "8000")))
