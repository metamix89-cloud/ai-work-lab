import csv
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

BASE = Path(__file__).parent
SEED = BASE / "seed"
DB = BASE / "biz.db"

SCHEMA = {
    "biz_users": ("users.csv", ["user_id", "name", "role"]),
    "biz_orders": ("orders.csv", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "biz_stock": ("stock.csv", ["sku", "name", "qty", "safety_qty"]),
    "biz_inquiries": ("inquiries.csv", ["inquiry_id", "received_at", "channel", "status"]),
}
INT_COLS = {"amount", "qty", "safety_qty"}

VISIBLE = {
    "exec": ["orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries"],
    "sales": ["orders", "revenue", "cancel_rate", "open_inquiries"],
    "logistics": ["orders", "stock_alerts"],
}


def build_db():
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    for table, (fname, cols) in SCHEMA.items():
        defs = ", ".join(f"{c} INTEGER" if c in INT_COLS else f"{c} TEXT" for c in cols)
        con.execute(f"CREATE TABLE {table} ({defs})")
        with open(SEED / fname, encoding="utf-8-sig", newline="") as f:
            rows = [
                [int(r[c]) if c in INT_COLS else r[c].strip() for c in cols]
                for r in csv.DictReader(f)
            ]
        con.executemany(
            f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})", rows
        )
    con.commit()
    con.close()


build_db()
app = FastAPI()


def reject(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def parse_day(s):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def query(sql, args=()):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/users")
def users():
    rows = query("SELECT user_id, name, role FROM biz_users ORDER BY rowid")
    return [{"user_id": a, "name": b, "role": c} for a, b, c in rows]


@app.get("/api/dashboard")
def dashboard(
    viewer: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
):
    # 400 (입력만 보면 아는 것) 먼저, 그다음 404
    if not viewer:
        return reject(400, "사용자를 확인하세요")
    bad = "기간을 확인하세요"
    if not from_ and not to:
        end = date.today()
        start = end - timedelta(days=6)
    elif not from_ or not to:
        return reject(400, bad)
    else:
        start, end = parse_day(from_), parse_day(to)
        if start is None or end is None or start > end or (end - start).days + 1 > 31:
            return reject(400, bad)

    row = query("SELECT role FROM biz_users WHERE user_id = ?", (viewer,))
    if not row:
        return reject(404, "사용자를 찾을 수 없습니다")
    role = row[0][0]

    lo, hi = start.isoformat(), end.isoformat()
    day = "substr(ordered_at, 1, 10) BETWEEN ? AND ?"
    total, canceled, revenue = query(
        f"""SELECT COUNT(*),
                   COALESCE(SUM(status = '취소'), 0),
                   COALESCE(SUM(CASE WHEN status = '출고' THEN amount END), 0)
            FROM biz_orders WHERE {day}""",
        (lo, hi),
    )[0]
    all_metrics = {
        "orders": total - canceled,
        "revenue": revenue,
        "cancel_rate": round(canceled * 100 / total + 1e-9, 1) if total else None,
        "stock_alerts": query("SELECT COUNT(*) FROM biz_stock WHERE qty < safety_qty")[0][0],
        "open_inquiries": query(
            """SELECT COUNT(*) FROM biz_inquiries
               WHERE substr(received_at, 1, 10) BETWEEN ? AND ?
                 AND status IN ('접수', '처리중')""",
            (lo, hi),
        )[0][0],
    }
    counts = dict(
        query(
            f"""SELECT substr(ordered_at, 1, 10), COUNT(*) FROM biz_orders
                WHERE {day} AND status != '취소' GROUP BY 1""",
            (lo, hi),
        )
    )
    daily = []
    d = start
    while d <= end:
        daily.append({"date": d.isoformat(), "count": counts.get(d.isoformat(), 0)})
        d += timedelta(days=1)

    result = {
        "period": {"from": lo, "to": hi},
        "metrics": {k: all_metrics[k] for k in VISIBLE.get(role, [])},
        "daily": daily,
    }
    if role == "exec":
        result["top_customers"] = [
            {"customer": c, "revenue": r}
            for c, r in query(
                f"""SELECT customer, SUM(amount) AS r FROM biz_orders
                    WHERE {day} AND status = '출고'
                    GROUP BY customer ORDER BY r DESC, customer ASC LIMIT 5""",
                (lo, hi),
            )
        ]
    result["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return result
