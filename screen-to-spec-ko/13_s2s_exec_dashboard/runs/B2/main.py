import csv
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "seed")
DB = os.path.join(BASE, "biz.db")

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


def build_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    for table, (fname, cols, ints) in SCHEMA.items():
        defs = ", ".join(f"{c} {'INTEGER' if c in ints else 'TEXT'}" for c in cols)
        con.execute(f"CREATE TABLE {table} ({defs})")
        with open(os.path.join(SEED, fname), encoding="utf-8-sig", newline="") as f:
            rows = [
                [int(r[c]) if c in ints else r[c].strip() for c in cols]
                for r in csv.DictReader(f)
            ]
        con.executemany(
            f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})", rows
        )
    con.commit()
    con.close()


@asynccontextmanager
async def lifespan(app):
    build_db()
    yield


app = FastAPI(lifespan=lifespan)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    if not DATE_RE.match(s):
        raise ValueError
    return datetime.strptime(s, "%Y-%m-%d").date()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    con = db()
    rows = con.execute("SELECT user_id, name, role FROM biz_users ORDER BY rowid").fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/api/dashboard")
def dashboard(request: Request):
    q = request.query_params
    viewer = (q.get("viewer") or "").strip()
    frm, to = q.get("from"), q.get("to")

    # 본문 · 쿼리만 보면 아는 것(400) 먼저
    if not viewer:
        raise HTTPException(400, "사용자를 확인하세요")
    if not frm and not to:
        today = datetime.now().date()
        d_to, d_from = today, today - timedelta(days=6)
    else:
        try:
            if not frm or not to:
                raise ValueError
            d_from, d_to = parse_date(frm), parse_date(to)
        except ValueError:
            raise HTTPException(400, "기간을 확인하세요")
        if d_from > d_to or (d_to - d_from).days + 1 > 31:
            raise HTTPException(400, "기간을 확인하세요")

    con = db()
    user = con.execute("SELECT role FROM biz_users WHERE user_id = ?", (viewer,)).fetchone()
    if user is None:
        con.close()
        raise HTTPException(404, "사용자를 찾을 수 없습니다")
    role = user["role"]
    f, t = d_from.isoformat(), d_to.isoformat()

    def one(sql, *args):
        return con.execute(sql, args).fetchone()[0]

    in_period = "substr(ordered_at, 1, 10) BETWEEN ? AND ?"
    total = one(f"SELECT COUNT(*) FROM biz_orders WHERE {in_period}", f, t)
    cancelled = one(f"SELECT COUNT(*) FROM biz_orders WHERE {in_period} AND status = '취소'", f, t)
    all_metrics = {
        "orders": total - cancelled,
        "revenue": one(
            f"SELECT COALESCE(SUM(amount), 0) FROM biz_orders WHERE {in_period} AND status = '출고'", f, t
        ),
        "cancel_rate": round(cancelled * 100 / total + 1e-9, 1) if total else None,
        "stock_alerts": one("SELECT COUNT(*) FROM biz_stock WHERE qty < safety_qty"),
        "open_inquiries": one(
            "SELECT COUNT(*) FROM biz_inquiries WHERE substr(received_at, 1, 10) BETWEEN ? AND ? "
            "AND status IN ('접수', '처리중')", f, t
        ),
    }
    metrics = {k: all_metrics[k] for k in VISIBLE.get(role, [])}

    counts = dict(con.execute(
        f"SELECT substr(ordered_at, 1, 10), COUNT(*) FROM biz_orders WHERE {in_period} "
        "AND status != '취소' GROUP BY 1", (f, t)
    ).fetchall())
    daily = []
    d = d_from
    while d <= d_to:
        daily.append({"date": d.isoformat(), "count": counts.get(d.isoformat(), 0)})
        d += timedelta(days=1)

    result = {"period": {"from": f, "to": t}, "metrics": metrics, "daily": daily}
    if role == "exec":
        rows = con.execute(
            f"SELECT customer, SUM(amount) AS revenue FROM biz_orders WHERE {in_period} "
            "AND status = '출고' GROUP BY customer ORDER BY revenue DESC, customer ASC LIMIT 5", (f, t)
        ).fetchall()
        result["top_customers"] = [dict(r) for r in rows]
    result["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    con.close()
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=int(os.environ.get("PORT", 8000)))
