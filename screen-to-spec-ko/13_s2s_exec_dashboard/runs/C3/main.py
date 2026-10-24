import csv
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "biz.db")

TABLES = {
    "users": ("biz_users", ["user_id", "name", "role"]),
    "orders": ("biz_orders", ["order_id", "ordered_at", "customer", "amount", "status"]),
    "stock": ("biz_stock", ["sku", "name", "qty", "safety_qty"]),
    "inquiries": ("biz_inquiries", ["inquiry_id", "received_at", "channel", "status"]),
}
INT_COLS = {"amount", "qty", "safety_qty"}

ROLE_METRICS = {
    "exec": ["orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries"],
    "sales": ["orders", "revenue", "cancel_rate", "open_inquiries"],
    "logistics": ["orders", "stock_alerts"],
}


def load_seed():
    for p in (DB, DB + "-journal"):
        if os.path.exists(p):
            os.remove(p)
    con = sqlite3.connect(DB)
    for name, (table, cols) in TABLES.items():
        defs = ", ".join("%s %s" % (c, "INTEGER" if c in INT_COLS else "TEXT") for c in cols)
        con.execute("CREATE TABLE %s (%s)" % (table, defs))
        with open(os.path.join(BASE, "seed", name + ".csv"), encoding="utf-8-sig", newline="") as f:
            rows = [[int(r[c]) if c in INT_COLS else r[c] for c in cols] for r in csv.DictReader(f)]
        con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))), rows)
    con.commit()
    con.close()


load_seed()
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


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


@app.get("/api/users")
def users():
    con = db()
    try:
        return [dict(r) for r in con.execute("SELECT user_id, name, role FROM biz_users ORDER BY rowid")]
    finally:
        con.close()


@app.get("/api/dashboard")
def dashboard(viewer: str = Query(None), from_: str = Query(None, alias="from"), to: str = Query(None)):
    # R9: 쿼리만 보면 아는 거부(400)를 먼저, 없는 사용자(404)는 그다음
    if not viewer:
        return reject(400, "사용자를 확인하세요")
    if not from_ and not to:
        end = date.today()
        start = end - timedelta(days=6)
    elif not from_ or not to:
        return reject(400, "기간을 확인하세요")
    else:
        start, end = parse_day(from_), parse_day(to)
        if start is None or end is None or start > end or (end - start).days > 30:
            return reject(400, "기간을 확인하세요")
    con = db()
    try:
        user = con.execute("SELECT role FROM biz_users WHERE user_id=?", (viewer,)).fetchone()
        if user is None or user["role"] not in ROLE_METRICS:
            return reject(404, "사용자를 찾을 수 없습니다")
        role = user["role"]
        a, b = start.isoformat(), end.isoformat()
        # 날짜 부분만 비교해 종료일 당일 주문이 빠지지 않게 한다
        cond = "substr(ordered_at,1,10) BETWEEN ? AND ?"
        total, cancelled, orders, revenue = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(status='취소'),0), COALESCE(SUM(status<>'취소'),0),"
            " COALESCE(SUM(CASE WHEN status='출고' THEN amount END),0) FROM biz_orders WHERE " + cond,
            (a, b)).fetchone()
        all_m = {
            "orders": orders,
            "revenue": revenue,
            "cancel_rate": round(cancelled * 100.0 / total + 1e-9, 1) if total else None,
            "stock_alerts": con.execute("SELECT COUNT(*) FROM biz_stock WHERE qty < safety_qty").fetchone()[0],
            "open_inquiries": con.execute(
                "SELECT COUNT(*) FROM biz_inquiries WHERE status IN ('접수','처리중')"
                " AND substr(received_at,1,10) BETWEEN ? AND ?", (a, b)).fetchone()[0],
        }
        counts = {r[0]: r[1] for r in con.execute(
            "SELECT substr(ordered_at,1,10), COUNT(*) FROM biz_orders WHERE status<>'취소' AND " + cond
            + " GROUP BY 1", (a, b))}
        daily = []
        for i in range((end - start).days + 1):
            d = (start + timedelta(days=i)).isoformat()
            daily.append({"date": d, "count": counts.get(d, 0)})
        out = {"period": {"from": a, "to": b}, "metrics": {k: all_m[k] for k in ROLE_METRICS[role]}, "daily": daily}
        if role == "exec":
            out["top_customers"] = [
                {"customer": r[0], "revenue": r[1]} for r in con.execute(
                    "SELECT customer, SUM(amount) s FROM biz_orders WHERE status='출고' AND " + cond
                    + " GROUP BY customer ORDER BY s DESC, customer LIMIT 5", (a, b))]
        out["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        return out
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"), media_type="text/html; charset=utf-8")
