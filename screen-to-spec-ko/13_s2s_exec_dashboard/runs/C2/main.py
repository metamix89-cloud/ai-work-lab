import csv
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "biz.db")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

app = FastAPI()


def load_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE biz_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
    CREATE TABLE biz_orders (order_id TEXT PRIMARY KEY, ordered_at TEXT, customer TEXT, amount INTEGER, status TEXT);
    CREATE TABLE biz_stock (sku TEXT PRIMARY KEY, name TEXT, qty INTEGER, safety_qty INTEGER);
    CREATE TABLE biz_inquiries (inquiry_id TEXT PRIMARY KEY, received_at TEXT, channel TEXT, status TEXT);
    """)

    def read(name):
        with open(os.path.join(BASE, "seed", name), encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    con.executemany("INSERT INTO biz_users VALUES (?,?,?)",
                    [(r["user_id"], r["name"], r["role"]) for r in read("users.csv")])
    con.executemany("INSERT INTO biz_orders VALUES (?,?,?,?,?)",
                    [(r["order_id"], r["ordered_at"], r["customer"], int(r["amount"]), r["status"]) for r in read("orders.csv")])
    con.executemany("INSERT INTO biz_stock VALUES (?,?,?,?)",
                    [(r["sku"], r["name"], int(r["qty"]), int(r["safety_qty"])) for r in read("stock.csv")])
    con.executemany("INSERT INTO biz_inquiries VALUES (?,?,?,?)",
                    [(r["inquiry_id"], r["received_at"], r["channel"], r["status"]) for r in read("inquiries.csv")])
    con.commit()
    con.close()


load_db()


def query(sql, args=()):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@app.exception_handler(HTTPException)
async def http_exc(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    return [{"user_id": r[0], "name": r[1], "role": r[2]}
            for r in query("SELECT user_id, name, role FROM biz_users ORDER BY rowid")]


def parse_day(s):
    if not DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


VISIBLE = {
    "exec": ["orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries"],
    "sales": ["orders", "revenue", "cancel_rate", "open_inquiries"],
    "logistics": ["orders", "stock_alerts"],
}


@app.get("/api/dashboard")
def dashboard(request: Request):
    p = request.query_params
    viewer, frm, to = p.get("viewer"), p.get("from"), p.get("to")
    if not viewer:
        raise HTTPException(400, "사용자를 확인하세요")
    if frm is None and to is None:
        d_to = date.today()
        d_from = d_to - timedelta(days=6)
    else:
        d_from = parse_day(frm) if frm else None
        d_to = parse_day(to) if to else None
        if d_from is None or d_to is None or d_from > d_to or (d_to - d_from).days + 1 > 31:
            raise HTTPException(400, "기간을 확인하세요")
    rows = query("SELECT role FROM biz_users WHERE user_id=?", (viewer,))
    if not rows:
        raise HTTPException(404, "사용자를 찾을 수 없습니다")
    role = rows[0][0]
    keys = VISIBLE.get(role, [])
    f, t = d_from.isoformat(), d_to.isoformat()
    rng = "substr(ordered_at,1,10) BETWEEN ? AND ?"

    counts = {s: n for s, n in query(f"SELECT status, COUNT(*) FROM biz_orders WHERE {rng} GROUP BY status", (f, t))}
    total = sum(counts.values())
    canceled = counts.get("취소", 0)
    all_m = {
        "orders": total - canceled,
        "revenue": query(f"SELECT COALESCE(SUM(amount),0) FROM biz_orders WHERE {rng} AND status='출고'", (f, t))[0][0],
        "cancel_rate": round(canceled * 100.0 / total + 1e-9, 1) if total else None,
        "stock_alerts": query("SELECT COUNT(*) FROM biz_stock WHERE qty < safety_qty")[0][0],
        "open_inquiries": query("SELECT COUNT(*) FROM biz_inquiries WHERE substr(received_at,1,10) BETWEEN ? AND ? "
                                "AND status IN ('접수','처리중')", (f, t))[0][0],
    }
    per_day = {d: n for d, n in query(f"SELECT substr(ordered_at,1,10), COUNT(*) FROM biz_orders WHERE {rng} "
                                      "AND status!='취소' GROUP BY 1", (f, t))}
    daily = []
    cur = d_from
    while cur <= d_to:
        daily.append({"date": cur.isoformat(), "count": per_day.get(cur.isoformat(), 0)})
        cur += timedelta(days=1)

    out = {"period": {"from": f, "to": t}, "metrics": {k: all_m[k] for k in keys}, "daily": daily}
    if role == "exec":
        out["top_customers"] = [{"customer": c, "revenue": r} for c, r in query(
            f"SELECT customer, SUM(amount) s FROM biz_orders WHERE {rng} AND status='출고' "
            "GROUP BY customer ORDER BY s DESC, customer ASC LIMIT 5", (f, t))]
    out["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return out
